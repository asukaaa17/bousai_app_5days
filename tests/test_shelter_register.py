from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app import app


def test_register_shelter_success_message():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True

    response = client.post('/shelter_register', data={'name': '新しい避難所'})
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '避難所を登録しました' in html


def test_register_shelter_empty_name_error_message():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True

    response = client.post('/shelter_register', data={'name': '   '})
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '避難所名を入力してください' in html


def test_parse_weather_warning_with_jma_format(monkeypatch):
    fake_data = [{
        'reportDatetime': '2026-10-04T09:00:00+09:00',
        'warning': {
            'class20Items': [
                {'areaCode': '0220100', 'kinds': [{'status': '発表', 'code': '03'}]},
                {'areaCode': '0220500', 'kinds': [{'status': '解除', 'code': '10'}]},
            ]
        }
    }]

    class FakeResponse:
        def __init__(self, payload):
            self.payload = json.dumps(payload).encode('utf-8')

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.payload

    monkeypatch.setattr(app_module.urllib.request, 'urlopen', lambda url, timeout=10: FakeResponse(fake_data))

    weather = app_module.get_weather_warnings()

    assert weather['warnings'] == [{
        'name': 'レベル3大雨警報',
        'code': '03',
        'status': '発表'
    }]
