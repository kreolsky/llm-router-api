"""Byte-level golden for every /stat/api/* JSON endpoint over a seeded DB.

The expected bodies were captured from the index-mapped queries before the
row-factory rewrite; any drift in keys, key order, types or values fails here.
Rows are INSERTed directly so the golden does not depend on the writer's API.
"""

import httpx
import pytest
from fastapi import FastAPI
from pytest_asyncio import fixture as asyncio_fixture

from src.api.stat_routes import router as stat_router
from src.core import usage_db

_T0 = 1_750_000_000.0  # 2025-06-15 15:06:40 UTC
_DAY = 86400.0

# (request_id, project, model, provider, endpoint, ts, prompt, completion, cached,
#  reasoning, total, duration_ms, status, error_code, error_message, key_hash,
#  client_ip, cost_usd, has_usage, stream)
_ROWS = [
    ("r1", "alice", "m1", "p1", "chat", _T0, 100, 30, 50, 5, 130, 120.5, 200,
     None, None, "hash-a", "10.0.0.1", 1.6e-4, 1, 1),
    ("r2", "bob", "m2", "p2", "chat", _T0 + 60, 100, 10, 0, 0, 110, 80.0, 200,
     None, None, "hash-b", "10.0.0.2", None, 1, 0),
    ("r3", "unknown", "", "", "chat", _T0 + 120, 0, 0, 0, 0, 0, 3.25, 401,
     "invalid_api_key", "Invalid API key", "hash-x", "10.0.0.3", None, 0, 0),
    ("r4", "carol", "m3", "p3", "embeddings", _T0 + _DAY, 40, 0, 0, 0, 40, 15.0, 422,
     None, "validation failed", "hash-c", "10.0.0.4", None, 0, 0),
    ("r5", "alice", "m1", "p1", "chat", _T0 + _DAY + 30, 300, 90, 100, 20, 390, 900.0, 200,
     "provider_stream_error", "peg-native", "hash-a", "10.0.0.1", 4.4e-4, 1, 1),
    ("r6", "bob", "m1", "p1", "chat", _T0 + 2 * _DAY, 10, 5, 0, 0, 15, 50.0, 200,
     None, None, "hash-b", "10.0.0.2", 2.0e-5, 1, 0),
]

_INSERT = """INSERT INTO usage_events
    (request_id, project_name, model_id, provider_name, endpoint, timestamp,
     prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, total_tokens,
     duration_ms, status_code, error_code, error_message, api_key_hash, client_ip,
     cost_usd, has_usage, stream)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

_QUERIES = [
    "/stat/api/users",
    "/stat/api/models",
    "/stat/api/usage",
    "/stat/api/usage?users=alice,bob&models=m1",
    "/stat/api/summary",
    "/stat/api/summary?users=alice&models=m1",
    # A filter matching no row: the SUMs are NULL here, so the 0-coalescing is pinned.
    "/stat/api/usage?users=__nobody__",
    "/stat/api/summary?users=__nobody__",
    "/stat/api/requests",
    "/stat/api/requests?status=error",
    "/stat/api/requests?status=ok&providers=p1",
    "/stat/api/requests?error_code=none",
    "/stat/api/requests?error_code=invalid_api_key",
    "/stat/api/requests?request_id=r5",
    "/stat/api/requests?limit=2&offset=1",
]

GOLDEN: dict[str, bytes] = {
    '/stat/api/usage?users=__nobody__': (
        b'{"series":[]}'
    ),
    '/stat/api/summary?users=__nobody__': (
        b'{"totals":{"requests":0,"errors":0,"error_rate":0.0,"prompt_tokens":0,"cached_to'
        b'kens":0,"completion_tokens":0,"reasoning_tokens":0,"total_tokens":0,"cost_usd":n'
        b'ull,"unpriced":0,"cache_hit_rate":0.0},"by_user":[],"by_model":[],"by_provider":'
        b'[],"by_error_code":[],"by_day":[]}'
    ),
    '/stat/api/users': (
        b'["alice","bob","carol","unknown"]'
    ),
    '/stat/api/models': (
        b'["","m1","m2","m3"]'
    ),
    '/stat/api/usage': (
        b'{"series":[{"user":"alice","model":"m1","dates":["2025-06-15","2025-06-16","2025'
        b'-06-17"],"prompt":[100,300,0],"cached":[50,100,0],"completion":[30,90,0]},{"user'
        b'":"bob","model":"m1","dates":["2025-06-15","2025-06-16","2025-06-17"],"prompt":['
        b'0,0,10],"cached":[0,0,0],"completion":[0,0,5]},{"user":"bob","model":"m2","dates'
        b'":["2025-06-15","2025-06-16","2025-06-17"],"prompt":[100,0,0],"cached":[0,0,0],"'
        b'completion":[10,0,0]},{"user":"carol","model":"m3","dates":["2025-06-15","2025-0'
        b'6-16","2025-06-17"],"prompt":[0,40,0],"cached":[0,0,0],"completion":[0,0,0]},{"u'
        b'ser":"unknown","model":"","dates":["2025-06-15","2025-06-16","2025-06-17"],"prom'
        b'pt":[0,0,0],"cached":[0,0,0],"completion":[0,0,0]}]}'
    ),
    '/stat/api/usage?users=alice,bob&models=m1': (
        b'{"series":[{"user":"alice","model":"m1","dates":["2025-06-15","2025-06-16","2025'
        b'-06-17"],"prompt":[100,300,0],"cached":[50,100,0],"completion":[30,90,0]},{"user'
        b'":"bob","model":"m1","dates":["2025-06-15","2025-06-16","2025-06-17"],"prompt":['
        b'0,0,10],"cached":[0,0,0],"completion":[0,0,5]}]}'
    ),
    '/stat/api/summary': (
        b'{"totals":{"requests":6,"errors":3,"error_rate":0.5,"prompt_tokens":550,"cached_'
        b'tokens":150,"completion_tokens":135,"reasoning_tokens":25,"total_tokens":685,"co'
        b'st_usd":0.00062,"unpriced":2,"cache_hit_rate":0.2727272727272727},"by_user":[{"u'
        b'ser":"alice","requests":2,"errors":1,"prompt_tokens":400,"cached_tokens":150,"co'
        b'mpletion_tokens":120,"total_tokens":520,"cost_usd":0.0006000000000000001},{"user'
        b'":"bob","requests":2,"errors":0,"prompt_tokens":110,"cached_tokens":0,"completio'
        b'n_tokens":15,"total_tokens":125,"cost_usd":2e-05},{"user":"carol","requests":1,"'
        b'errors":1,"prompt_tokens":40,"cached_tokens":0,"completion_tokens":0,"total_toke'
        b'ns":40,"cost_usd":null},{"user":"unknown","requests":1,"errors":1,"prompt_tokens'
        b'":0,"cached_tokens":0,"completion_tokens":0,"total_tokens":0,"cost_usd":null}],"'
        b'by_model":[{"model":"m1","requests":3,"errors":1,"prompt_tokens":410,"cached_tok'
        b'ens":150,"completion_tokens":125,"total_tokens":535,"cost_usd":0.00062},{"model"'
        b':"m2","requests":1,"errors":0,"prompt_tokens":100,"cached_tokens":0,"completion_'
        b'tokens":10,"total_tokens":110,"cost_usd":null},{"model":"m3","requests":1,"error'
        b's":1,"prompt_tokens":40,"cached_tokens":0,"completion_tokens":0,"total_tokens":4'
        b'0,"cost_usd":null},{"model":"","requests":1,"errors":1,"prompt_tokens":0,"cached'
        b'_tokens":0,"completion_tokens":0,"total_tokens":0,"cost_usd":null}],"by_provider'
        b'":[{"provider":"p1","requests":3,"errors":1,"prompt_tokens":410,"cached_tokens":'
        b'150,"completion_tokens":125,"total_tokens":535,"cost_usd":0.00062},{"provider":"'
        b'p2","requests":1,"errors":0,"prompt_tokens":100,"cached_tokens":0,"completion_to'
        b'kens":10,"total_tokens":110,"cost_usd":null},{"provider":"p3","requests":1,"erro'
        b'rs":1,"prompt_tokens":40,"cached_tokens":0,"completion_tokens":0,"total_tokens":'
        b'40,"cost_usd":null},{"provider":"","requests":1,"errors":1,"prompt_tokens":0,"ca'
        b'ched_tokens":0,"completion_tokens":0,"total_tokens":0,"cost_usd":null}],"by_erro'
        b'r_code":[{"error_code":"provider_stream_error","count":1},{"error_code":"invalid'
        b'_api_key","count":1},{"error_code":null,"count":1}],"by_day":[{"day":"2025-06-15'
        b'","requests":3,"errors":1,"prompt_tokens":200,"cached_tokens":50,"completion_tok'
        b'ens":40,"cost_usd":0.00016},{"day":"2025-06-16","requests":2,"errors":2,"prompt_'
        b'tokens":340,"cached_tokens":100,"completion_tokens":90,"cost_usd":0.00044},{"day'
        b'":"2025-06-17","requests":1,"errors":0,"prompt_tokens":10,"cached_tokens":0,"com'
        b'pletion_tokens":5,"cost_usd":2e-05}]}'
    ),
    '/stat/api/summary?users=alice&models=m1': (
        b'{"totals":{"requests":2,"errors":1,"error_rate":0.5,"prompt_tokens":400,"cached_'
        b'tokens":150,"completion_tokens":120,"reasoning_tokens":25,"total_tokens":520,"co'
        b'st_usd":0.0006000000000000001,"unpriced":0,"cache_hit_rate":0.375},"by_user":[{"'
        b'user":"alice","requests":2,"errors":1,"prompt_tokens":400,"cached_tokens":150,"c'
        b'ompletion_tokens":120,"total_tokens":520,"cost_usd":0.0006000000000000001}],"by_'
        b'model":[{"model":"m1","requests":2,"errors":1,"prompt_tokens":400,"cached_tokens'
        b'":150,"completion_tokens":120,"total_tokens":520,"cost_usd":0.000600000000000000'
        b'1}],"by_provider":[{"provider":"p1","requests":2,"errors":1,"prompt_tokens":400,'
        b'"cached_tokens":150,"completion_tokens":120,"total_tokens":520,"cost_usd":0.0006'
        b'000000000000001}],"by_error_code":[{"error_code":"provider_stream_error","count"'
        b':1}],"by_day":[{"day":"2025-06-15","requests":1,"errors":0,"prompt_tokens":100,"'
        b'cached_tokens":50,"completion_tokens":30,"cost_usd":0.00016},{"day":"2025-06-16"'
        b',"requests":1,"errors":1,"prompt_tokens":300,"cached_tokens":100,"completion_tok'
        b'ens":90,"cost_usd":0.00044}]}'
    ),
    '/stat/api/requests': (
        b'{"requests":[{"id":6,"request_id":"r6","timestamp":1750172800.0,"project_name":"'
        b'bob","model_id":"m1","provider_name":"p1","endpoint":"chat","stream":false,"prom'
        b'pt_tokens":10,"completion_tokens":5,"cached_tokens":0,"reasoning_tokens":0,"tota'
        b'l_tokens":15,"cost_usd":2e-05,"duration_ms":50.0,"status_code":200,"error_code":'
        b'null,"error_message":null,"api_key_hash":"hash-b","client_ip":"10.0.0.2"},{"id":'
        b'5,"request_id":"r5","timestamp":1750086430.0,"project_name":"alice","model_id":"'
        b'm1","provider_name":"p1","endpoint":"chat","stream":true,"prompt_tokens":300,"co'
        b'mpletion_tokens":90,"cached_tokens":100,"reasoning_tokens":20,"total_tokens":390'
        b',"cost_usd":0.00044,"duration_ms":900.0,"status_code":200,"error_code":"provider'
        b'_stream_error","error_message":"peg-native","api_key_hash":"hash-a","client_ip":'
        b'"10.0.0.1"},{"id":4,"request_id":"r4","timestamp":1750086400.0,"project_name":"c'
        b'arol","model_id":"m3","provider_name":"p3","endpoint":"embeddings","stream":fals'
        b'e,"prompt_tokens":40,"completion_tokens":0,"cached_tokens":0,"reasoning_tokens":'
        b'0,"total_tokens":40,"cost_usd":null,"duration_ms":15.0,"status_code":422,"error_'
        b'code":null,"error_message":"validation failed","api_key_hash":"hash-c","client_i'
        b'p":"10.0.0.4"},{"id":3,"request_id":"r3","timestamp":1750000120.0,"project_name"'
        b':"unknown","model_id":"","provider_name":"","endpoint":"chat","stream":false,"pr'
        b'ompt_tokens":0,"completion_tokens":0,"cached_tokens":0,"reasoning_tokens":0,"tot'
        b'al_tokens":0,"cost_usd":null,"duration_ms":3.25,"status_code":401,"error_code":"'
        b'invalid_api_key","error_message":"Invalid API key","api_key_hash":"hash-x","clie'
        b'nt_ip":"10.0.0.3"},{"id":2,"request_id":"r2","timestamp":1750000060.0,"project_n'
        b'ame":"bob","model_id":"m2","provider_name":"p2","endpoint":"chat","stream":false'
        b',"prompt_tokens":100,"completion_tokens":10,"cached_tokens":0,"reasoning_tokens"'
        b':0,"total_tokens":110,"cost_usd":null,"duration_ms":80.0,"status_code":200,"erro'
        b'r_code":null,"error_message":null,"api_key_hash":"hash-b","client_ip":"10.0.0.2"'
        b'},{"id":1,"request_id":"r1","timestamp":1750000000.0,"project_name":"alice","mod'
        b'el_id":"m1","provider_name":"p1","endpoint":"chat","stream":true,"prompt_tokens"'
        b':100,"completion_tokens":30,"cached_tokens":50,"reasoning_tokens":5,"total_token'
        b's":130,"cost_usd":0.00016,"duration_ms":120.5,"status_code":200,"error_code":nul'
        b'l,"error_message":null,"api_key_hash":"hash-a","client_ip":"10.0.0.1"}],"total":'
        b'6}'
    ),
    '/stat/api/requests?status=error': (
        b'{"requests":[{"id":5,"request_id":"r5","timestamp":1750086430.0,"project_name":"'
        b'alice","model_id":"m1","provider_name":"p1","endpoint":"chat","stream":true,"pro'
        b'mpt_tokens":300,"completion_tokens":90,"cached_tokens":100,"reasoning_tokens":20'
        b',"total_tokens":390,"cost_usd":0.00044,"duration_ms":900.0,"status_code":200,"er'
        b'ror_code":"provider_stream_error","error_message":"peg-native","api_key_hash":"h'
        b'ash-a","client_ip":"10.0.0.1"},{"id":4,"request_id":"r4","timestamp":1750086400.'
        b'0,"project_name":"carol","model_id":"m3","provider_name":"p3","endpoint":"embedd'
        b'ings","stream":false,"prompt_tokens":40,"completion_tokens":0,"cached_tokens":0,'
        b'"reasoning_tokens":0,"total_tokens":40,"cost_usd":null,"duration_ms":15.0,"statu'
        b's_code":422,"error_code":null,"error_message":"validation failed","api_key_hash"'
        b':"hash-c","client_ip":"10.0.0.4"},{"id":3,"request_id":"r3","timestamp":17500001'
        b'20.0,"project_name":"unknown","model_id":"","provider_name":"","endpoint":"chat"'
        b',"stream":false,"prompt_tokens":0,"completion_tokens":0,"cached_tokens":0,"reaso'
        b'ning_tokens":0,"total_tokens":0,"cost_usd":null,"duration_ms":3.25,"status_code"'
        b':401,"error_code":"invalid_api_key","error_message":"Invalid API key","api_key_h'
        b'ash":"hash-x","client_ip":"10.0.0.3"}],"total":3}'
    ),
    '/stat/api/requests?status=ok&providers=p1': (
        b'{"requests":[{"id":6,"request_id":"r6","timestamp":1750172800.0,"project_name":"'
        b'bob","model_id":"m1","provider_name":"p1","endpoint":"chat","stream":false,"prom'
        b'pt_tokens":10,"completion_tokens":5,"cached_tokens":0,"reasoning_tokens":0,"tota'
        b'l_tokens":15,"cost_usd":2e-05,"duration_ms":50.0,"status_code":200,"error_code":'
        b'null,"error_message":null,"api_key_hash":"hash-b","client_ip":"10.0.0.2"},{"id":'
        b'1,"request_id":"r1","timestamp":1750000000.0,"project_name":"alice","model_id":"'
        b'm1","provider_name":"p1","endpoint":"chat","stream":true,"prompt_tokens":100,"co'
        b'mpletion_tokens":30,"cached_tokens":50,"reasoning_tokens":5,"total_tokens":130,"'
        b'cost_usd":0.00016,"duration_ms":120.5,"status_code":200,"error_code":null,"error'
        b'_message":null,"api_key_hash":"hash-a","client_ip":"10.0.0.1"}],"total":2}'
    ),
    '/stat/api/requests?error_code=none': (
        b'{"requests":[{"id":4,"request_id":"r4","timestamp":1750086400.0,"project_name":"'
        b'carol","model_id":"m3","provider_name":"p3","endpoint":"embeddings","stream":fal'
        b'se,"prompt_tokens":40,"completion_tokens":0,"cached_tokens":0,"reasoning_tokens"'
        b':0,"total_tokens":40,"cost_usd":null,"duration_ms":15.0,"status_code":422,"error'
        b'_code":null,"error_message":"validation failed","api_key_hash":"hash-c","client_'
        b'ip":"10.0.0.4"}],"total":1}'
    ),
    '/stat/api/requests?error_code=invalid_api_key': (
        b'{"requests":[{"id":3,"request_id":"r3","timestamp":1750000120.0,"project_name":"'
        b'unknown","model_id":"","provider_name":"","endpoint":"chat","stream":false,"prom'
        b'pt_tokens":0,"completion_tokens":0,"cached_tokens":0,"reasoning_tokens":0,"total'
        b'_tokens":0,"cost_usd":null,"duration_ms":3.25,"status_code":401,"error_code":"in'
        b'valid_api_key","error_message":"Invalid API key","api_key_hash":"hash-x","client'
        b'_ip":"10.0.0.3"}],"total":1}'
    ),
    '/stat/api/requests?request_id=r5': (
        b'{"requests":[{"id":5,"request_id":"r5","timestamp":1750086430.0,"project_name":"'
        b'alice","model_id":"m1","provider_name":"p1","endpoint":"chat","stream":true,"pro'
        b'mpt_tokens":300,"completion_tokens":90,"cached_tokens":100,"reasoning_tokens":20'
        b',"total_tokens":390,"cost_usd":0.00044,"duration_ms":900.0,"status_code":200,"er'
        b'ror_code":"provider_stream_error","error_message":"peg-native","api_key_hash":"h'
        b'ash-a","client_ip":"10.0.0.1"}],"total":1}'
    ),
    '/stat/api/requests?limit=2&offset=1': (
        b'{"requests":[{"id":5,"request_id":"r5","timestamp":1750086430.0,"project_name":"'
        b'alice","model_id":"m1","provider_name":"p1","endpoint":"chat","stream":true,"pro'
        b'mpt_tokens":300,"completion_tokens":90,"cached_tokens":100,"reasoning_tokens":20'
        b',"total_tokens":390,"cost_usd":0.00044,"duration_ms":900.0,"status_code":200,"er'
        b'ror_code":"provider_stream_error","error_message":"peg-native","api_key_hash":"h'
        b'ash-a","client_ip":"10.0.0.1"},{"id":4,"request_id":"r4","timestamp":1750086400.'
        b'0,"project_name":"carol","model_id":"m3","provider_name":"p3","endpoint":"embedd'
        b'ings","stream":false,"prompt_tokens":40,"completion_tokens":0,"cached_tokens":0,'
        b'"reasoning_tokens":0,"total_tokens":40,"cost_usd":null,"duration_ms":15.0,"statu'
        b's_code":422,"error_code":null,"error_message":"validation failed","api_key_hash"'
        b':"hash-c","client_ip":"10.0.0.4"}],"total":6}'
    ),
}


@asyncio_fixture
async def client(tmp_path):
    # Costs are seeded verbatim in _ROWS; no row is priced at write time here.
    await usage_db.init_db(str(tmp_path / "usage.db"), lambda model_id: None)
    conn = usage_db.get_connection()
    await conn.executemany(_INSERT, _ROWS)
    await conn.commit()
    app = FastAPI()
    app.include_router(stat_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c
    await usage_db.close_db()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _QUERIES)
async def test_body_is_byte_identical(client, path):
    response = await client.get(path)
    assert response.status_code == 200
    assert response.content == GOLDEN[path]
