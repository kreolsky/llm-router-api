"""Base service with shared validation, provider instantiation, and logging."""
# SYSTEM: service-layer — validate access, resolve provider, dispatch

import contextlib
from dataclasses import dataclass, fields
from typing import Any

from fastapi import HTTPException, Request

from ..core.config_manager import ConfigManager
from ..core.context import AuthContext, RequestContext, request_context
from ..core.error_handling import ErrorType, create_error
from ..core.header_policy import (
    FORWARDED_HEADER_DENY_PREFIXES,
    FORWARDED_HEADER_DENYLIST,
)
from ..core.logging import logger
from ..core.usage_db import RequestStats, request_stats
from ..providers import get_provider_instance
from ..providers.base import BaseProvider
from .reasoning_effort import apply_reasoning_effort


@dataclass(frozen=True)
class ResolvedTarget:
    """Result of the body-agnostic dispatch resolver (BaseService._resolve_target).

    Everything a dispatch needs once the model id is known: validated config,
    the registry's provider instance, and the per-request identity headers.
    Carries no request body — JSON (chat/embeddings) and multipart
    (transcription) dispatches both ride it, so a cross-cutting policy added
    here reaches every endpoint by construction.
    """
    request_id: str
    user_id: str
    stats: RequestStats
    error_ctx: dict[str, Any]
    model_config: dict[str, Any]
    provider_name: str
    provider_model_name: str
    provider_config: dict[str, Any]
    provider: BaseProvider
    identity_headers: dict[str, str] | None


@dataclass(frozen=True)
class PreparedDispatch(ResolvedTarget):
    """Result of the shared service preamble (BaseService._prepare_dispatch).

    The JSON wrapper around ResolvedTarget: adds the parsed body and the
    requested model, and applies the reasoning-effort policy (a body-shaped
    concern that must NOT ride the shared resolver — multipart endpoints
    carry no such policy).
    """
    request_body: dict[str, Any]
    requested_model: str | None


class BaseService:
    """Common base for ChatService, EmbeddingService, ModelService, and TranscriptionService."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    @contextlib.asynccontextmanager
    async def _guard_service_errors(self, error_ctx: dict[str, Any]):
        """Wrap a service block: re-raise HTTPException as-is, wrap other errors.

        De-duplicates the identical try/except error-wrapping pattern across
        chat/embedding/transcription services.
        """
        try:
            yield
        except HTTPException:
            raise
        except Exception as e:
            raise create_error(
                ErrorType.INTERNAL_SERVER_ERROR,
                original_exception=e,
                error_details=str(e),
                **error_ctx,
            ) from e

    def _get_request_context(self, request: Request | None) -> RequestContext:
        """Return the typed RequestContext carried by the request."""
        return request_context(request)

    def _extract_passthrough_headers(self, request: Request | None) -> dict[str, str]:
        """Collect every client header minus the denylist (core/header_policy.py).

        WHY: passthrough forwards headers verbatim (the client's own spelling —
        casing is part of a harness fingerprint), so there is no whitelist to
        apply; the denylist is what keeps client credentials, stale transport
        values, and lab topology from going upstream.
        """
        if request is None:
            return {}
        forwarded: dict[str, str] = {}
        for name, value in request.headers.items():
            low = name.lower()
            if low in FORWARDED_HEADER_DENYLIST:
                continue
            if any(low.startswith(prefix) for prefix in FORWARDED_HEADER_DENY_PREFIXES):
                continue
            forwarded[name] = value
        return forwarded

    def _build_identity_headers(self, provider_instance: Any,
                                 request: Request | None) -> dict[str, str] | None:
        """Per-request upstream headers for providers with an identity profile.

        passthrough: forward the client's headers verbatim minus the denylist.
        Returns None when the provider has no profile (behavior unchanged).
        """
        identity = getattr(provider_instance, "identity", None)
        if not identity:
            return None
        return self._extract_passthrough_headers(request) or None

    def _validate_and_get_config(
        self,
        requested_model: str,
        auth_context: AuthContext,
        **error_context
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        """Validate model access and return (model_config, provider_name, provider_model_name, provider_config)."""
        allowed_models = auth_context.allowed_models

        if not requested_model:
            raise create_error(ErrorType.MODEL_NOT_SPECIFIED, **error_context)

        # INVARIANT: check allowed_models BEFORE checking existence to prevent
        # information leakage about configured models
        if allowed_models and requested_model not in allowed_models:
            raise create_error(ErrorType.MODEL_NOT_ALLOWED, **error_context)

        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)

        if not model_config:
            raise create_error(ErrorType.MODEL_NOT_FOUND, **error_context)

        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)
        provider_config = current_config.get("providers", {}).get(provider_name)

        if not provider_config:
            raise create_error(ErrorType.PROVIDER_NOT_FOUND, provider_name=provider_name, **error_context)

        return model_config, provider_name, provider_model_name, provider_config

    async def _parse_json_request(self, request: Request) -> dict[str, Any]:
        """Parse the JSON request body, answering 400 on malformed input."""
        try:
            return await request.json()
        # WHY: ValueError, not json.JSONDecodeError — invalid UTF-8 bodies raise
        # UnicodeDecodeError (also a ValueError) and must answer 400, not 500
        except ValueError:
            ctx = self._get_request_context(request)
            # from None: the client's own malformed body is the whole story
            raise create_error(ErrorType.MISSING_REQUIRED_FIELD, field_name="valid JSON body",
                             request_id=ctx.request_id, user_id=ctx.user_id) from None

    async def _resolve_target(
        self,
        request: Request,
        auth_context: AuthContext,
        model_id: Any,
    ) -> ResolvedTarget:
        """Body-agnostic dispatch funnel: enrich stats, validate access,
        resolve the provider, and build the identity headers.

        A non-string model id (client sent JSON garbage) reaches the usage row
        as "" but keeps its raw value in error_ctx — the error messages quote
        what the client actually sent.

        INVARIANT: identity_headers is computed exactly ONCE per request here,
        and the SAME object feeds the stream and non-stream branches.
        Why: the provider layer requires both paths to send an identical set
        (providers/base.py _merge_request_headers ARCH), and a per-branch
        recompute would hold that by luck, not by construction.
        """
        ctx = self._get_request_context(request)
        request_id = ctx.request_id
        user_id = ctx.user_id

        stats = request_stats(request)
        stats.model_id = model_id if isinstance(model_id, str) else ""

        error_ctx = {"request_id": request_id, "user_id": user_id, "model_id": model_id}

        model_config, provider_name, provider_model_name, provider_config = \
            self._validate_and_get_config(model_id, auth_context, **error_ctx)
        stats.provider_name = provider_name

        provider_instance = await get_provider_instance(provider_name)
        identity_headers = self._build_identity_headers(provider_instance, request)

        return ResolvedTarget(
            request_id=request_id, user_id=user_id, stats=stats, error_ctx=error_ctx,
            model_config=model_config, provider_name=provider_name,
            provider_model_name=provider_model_name, provider_config=provider_config,
            provider=provider_instance, identity_headers=identity_headers,
        )

    async def _prepare_dispatch(
        self,
        request: Request,
        auth_context: AuthContext,
        *,
        component: str,
        log_title: str,
    ) -> PreparedDispatch:
        """Thin JSON wrapper over _resolve_target: parse the body, log it,
        delegate, then apply the reasoning-effort policy to the parsed body.

        The effort policy is deliberately HERE and not in the resolver: it is
        body-shaped (reads/writes the JSON body), and multipart endpoints
        riding the resolver must never get it.
        """
        request_body = await self._parse_json_request(request)
        requested_model = request_body.get("model")

        self._log_service_data(title=log_title, data=request_body,
                               request_id=self._get_request_context(request).request_id,
                               component=component, data_flow="incoming")

        target = await self._resolve_target(request, auth_context, requested_model)

        # ARCH: the effort policy rides the one dispatch funnel (services/reasoning_effort.py).
        request_body = apply_reasoning_effort(request_body, target.model_config, **target.error_ctx)

        # Fields are DERIVED from ResolvedTarget, not re-listed: a field added
        # to the resolver reaches the JSON wrapper without a second edit.
        return PreparedDispatch(
            request_body=request_body, requested_model=requested_model,
            **{f.name: getattr(target, f.name) for f in fields(ResolvedTarget)},
        )

    def _log_service_data(
        self,
        title: str,
        data: Any,
        request_id: str,
        component: str,
        data_flow: str = "incoming"
    ) -> None:
        """Log request/response data via debug_data."""
        logger.debug_data(
            title=title,
            data=data,
            request_id=request_id,
            component=component,
            data_flow=data_flow
        )
