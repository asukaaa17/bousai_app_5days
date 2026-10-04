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


def test_home_page_shows_official_aomori_evacuation_notices(monkeypatch):
    monkeypatch.setattr(app_module, 'get_aomori_evacuation_info', lambda: {
        'notices': [{
            'content': '青森地区に避難指示を発令しました',
            'created_at': '青森市公式発表',
            'shelter': '',
            'is_urgent': True,
        }],
        'status_message': '',
        'error': False,
        'source_url': app_module.AOMORI_EVACUATION_URL,
    })
    client = app.test_client()
    response = client.get('/')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '青森市の避難情報' in html
    assert '青森地区に避難指示を発令しました' in html
    assert 'instruction-urgent' in html
    assert '片瀬小学校' not in html


def test_aomori_evacuation_parser_recognizes_no_active_information():
    page = '''
    <article id="content">
      <div id="voice"><h1>現在発表されている災害情報</h1></div>
      <p>現在、情報はありません。</p>
      <div id="reference"><p>お問い合わせ</p></div>
    </article>
    '''

    result = app_module.parse_aomori_evacuation_page(page)

    assert result['notices'] == []
    assert result['error'] is False
    assert '現在発表されている災害情報はありません' in result['status_message']


def test_aomori_evacuation_parser_extracts_active_notice_only():
        page = '''
        <article id="content">
            <div id="voice"><h1>現在発表されている災害情報</h1></div>
            <p class="update">ページ番号1002513 更新日 2026年10月4日</p>
            <ul><li>青森市A地区に避難指示を発令しました。</li></ul>
            <div id="reference"><p>問い合わせ 電話：017-734-5059</p></div>
        </article>
        '''

        result = app_module.parse_aomori_evacuation_page(page)

        assert result['error'] is False
        assert len(result['notices']) == 1
        assert result['notices'][0]['content'] == '青森市A地区に避難指示を発令しました。'
        assert result['notices'][0]['is_urgent'] is True


def test_disaster_notifications_use_aomori_weather_warnings(monkeypatch):
    monkeypatch.setattr(app_module, 'get_weather_warnings', lambda: {
        'area_name': '青森市',
        'warnings': [{'name': '暴風警報', 'code': '05', 'status': '発表'}],
        'report_time': '2026年10月04日 09:00',
        'last_fetch_time': '2026年10月04日 09:10',
    })

    items = app_module.get_disaster_notifications()

    assert len(items) == 1
    assert items[0]['area_name'] == '青森市'
    assert items[0]['kind'] == 'warning'
    assert items[0]['summary'] == '暴風警報（発表）'


def test_disaster_notifications_show_aomori_when_no_warnings(monkeypatch):
    monkeypatch.setattr(app_module, 'get_weather_warnings', lambda: {
        'area_name': '青森市',
        'warnings': [],
        'report_time': '2026年10月04日 09:00',
        'last_fetch_time': '2026年10月04日 09:10',
    })

    items = app_module.get_disaster_notifications()

    assert len(items) == 1
    assert items[0]['area_name'] == '青森市'
    assert items[0]['kind'] == 'info'
    assert items[0]['summary'] == '警報・注意報は発表されていません'
