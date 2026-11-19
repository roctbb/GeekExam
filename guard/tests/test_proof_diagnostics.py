import io
import json
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from guard_agent.transport import GuardClient
from guard_agent.rci import RouterError


@pytest.mark.parametrize('remote_code,expected',[
    ('connection_changed','connection_changed'),
    ('fresh_observation_required','fresh_observation_required'),
    ('secret-token-or-user-content',None),
])
def test_lan_diagnostics_expose_only_known_error_codes(remote_code,expected):
    client=GuardClient('https://guard.example.test','test-agent-token')
    error=HTTPError('https://guard.example.test',409,'Conflict',{},io.BytesIO(json.dumps({'error':remote_code}).encode()))
    with patch.object(client.opener,'open',side_effect=error),pytest.raises(RouterError) as result:
        client.post('proofs/inspect',{'token':'opaque-test-token'})
    assert str(result.value)=='guard_http_409'
    assert getattr(result.value,'proof_code',None)==expected
