from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 気象庁の市区町村コード（青森市）
AREA_CODES = ("0220100", "1420500")
AREA_CODE = AREA_CODES[0]

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')
NOTIFICATION_HISTORY_FILE = os.path.join(APP_DIR, 'data', 'notification_history.json')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def normalize_shelter(shelter, index=0):
    """避難所データに不足している項目を補完する"""
    if not isinstance(shelter, dict):
        return shelter

    normalized = dict(shelter)
    normalized['status'] = normalized.get('status', 'open')
    normalized['latitude'] = normalized.get('latitude')
    normalized['longitude'] = normalized.get('longitude')

    if normalized['latitude'] is None:
        normalized['latitude'] = 40.82 + (index % 5) * 0.012
    if normalized['longitude'] is None:
        normalized['longitude'] = 140.74 + (index % 4) * 0.013

    return normalized


shelters = [normalize_shelter(s, index) for index, s in enumerate(load_json(DATA_FILE, []))]
instructions = load_json(INSTRUCTIONS_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_shelters():
    """避難所データをファイルに保存する"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(shelters, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、なければ全件を返す"""
    return [s for s in shelters if not district or s.get('district') == district]


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") in AREA_CODES
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status in ("発表警報・注意報はなし", "なし", "解除"):
                continue
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


def parse_notification_time(value):
    """通知の時刻文字列を datetime に変換する"""
    if not value:
        return datetime.min.replace(tzinfo=JST)

    for fmt in (
        "%Y年%m月%d日 %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            if fmt.endswith('%z'):
                return datetime.strptime(value, fmt).astimezone(JST)
            return datetime.strptime(value, fmt).replace(tzinfo=JST)
        except ValueError:
            continue

    return datetime.min.replace(tzinfo=JST)


def get_disaster_kind(entry):
    """災害情報の種別を判定する"""
    if isinstance(entry, dict) and entry.get('has_emergency'):
        return 'emergency'
    if isinstance(entry, dict) and entry.get('has_warning'):
        return 'warning'
    if isinstance(entry, dict) and entry.get('has_advisory'):
        return 'advisory'
    return 'info'


def get_disaster_summary(entry):
    """災害情報の要約文を生成する"""
    if not isinstance(entry, dict):
        return '災害情報なし'

    warning_names = [
        warning.get('name', '')
        for warning in entry.get('warnings', [])
        if isinstance(warning, dict)
    ]
    if warning_names:
        return ' / '.join(warning_names)
    return '災害情報なし'


def parse_instruction_time(value):
    """指示の時刻文字列を datetime に変換する"""
    if not value:
        return datetime.min.replace(tzinfo=JST)

    for fmt in (
        "%Y年%m月%d日 %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            if fmt.endswith('%z'):
                return datetime.strptime(value, fmt).astimezone(JST)
            return datetime.strptime(value, fmt).replace(tzinfo=JST)
        except ValueError:
            continue

    return datetime.min.replace(tzinfo=JST)


def is_urgent_instruction(instruction):
    """避難や危険に関する住民向け指示を緊急扱いにする"""
    if not isinstance(instruction, dict):
        return False

    text = "{} {} {}".format(
        instruction.get('content', ''),
        instruction.get('shelter', ''),
        instruction.get('status', ''),
    ).lower()

    urgent_keywords = (
        '避難', '危険', '緊急', '土砂災害', '津波', '警戒', '避難指示', '高台',
        '警報', '特別警報', '浸水', '倒壊', '通行止め'
    )
    return any(keyword in text for keyword in urgent_keywords)


def get_resident_instructions():
    """住民向けの指示を新着順に取得し、緊急度も付与する"""
    resident_instructions = []
    for instruction in instructions:
        if instruction.get('target') != '住民':
            continue

        item = dict(instruction)
        item['is_urgent'] = is_urgent_instruction(item)
        item['priority_label'] = '緊急' if item['is_urgent'] else '通常'
        resident_instructions.append(item)

    resident_instructions.sort(
        key=lambda item: parse_instruction_time(item.get('created_at')),
        reverse=True,
    )
    return resident_instructions


def get_disaster_notifications(selected_type='all'):
    """新しい順に災害情報を取得する"""
    records = load_json(NOTIFICATION_HISTORY_FILE, [])
    sorted_records = sorted(
        records,
        key=lambda item: parse_notification_time(item.get('timestamp')),
        reverse=True,
    )

    items = []
    for record in sorted_records:
        kind = get_disaster_kind(record)
        if selected_type != 'all' and kind != selected_type:
            continue

        items.append({
            'kind': kind,
            'kind_label': {
                'emergency': '緊急',
                'warning': '警報',
                'advisory': '注意報',
                'info': '通常',
            }.get(kind, '通常'),
            'kind_icon': {
                'emergency': '🚨',
                'warning': '⚠️',
                'advisory': '📣',
                'info': 'ℹ️',
            }.get(kind, 'ℹ️'),
            'timestamp': record.get('timestamp', '不明'),
            'report_time': record.get('report_time', '不明'),
            'area_name': record.get('area_name', '不明'),
            'summary': get_disaster_summary(record),
            'warning_count': record.get('warning_count', 0),
        })

    return items


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = get_resident_instructions()
    selected_type = request.args.get('type', 'all')
    disaster_items = get_disaster_notifications(selected_type)
    emergency_notice = next((item for item in disaster_items if item['kind'] == 'emergency'), None)

    last_update = max(
        [parse_notification_time(item['timestamp']) for item in disaster_items],
        default=datetime.now(JST),
    )

    return render_template(
        'index.html',
        resident_notices=resident_notices,
        disaster_items=disaster_items,
        emergency_notice=emergency_notice,
        selected_type=selected_type,
        last_update=last_update.strftime('%Y年%m月%d日 %H:%M'),
        disaster_type_options=[
            ('all', '全て'),
            ('emergency', '緊急'),
            ('warning', '警報'),
            ('advisory', '注意報'),
            ('info', '通常'),
        ],
    )

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    success = False
    error = False
    message = ""

    if request.method == 'POST':
        shelter_name = request.form.get('name', '').strip()
        status = request.form.get('status', 'open')
        latitude = request.form.get('latitude', '').strip()
        longitude = request.form.get('longitude', '').strip()

        if shelter_name:
            shelter_id = max((s.get('id', 0) for s in shelters), default=0) + 1
            shelter = {
                'id': shelter_id,
                'name': shelter_name,
                'status': 'open' if status == 'open' else 'closed',
                'latitude': float(latitude) if latitude else 40.82 + (len(shelters) % 5) * 0.012,
                'longitude': float(longitude) if longitude else 140.74 + (len(shelters) % 4) * 0.013,
            }
            shelters.append(shelter)
            save_shelters()
            success = True
            message = '避難所を登録しました'
        else:
            error = True
            message = '避難所名を入力してください'

    return render_template('shelter_register.html', success=success, error=error, message=message)

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html')

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=shelters)


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board')
@login_required
def board():
    resident_instructions = get_resident_instructions()
    return render_template('board.html', instructions=resident_instructions)

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    results = filter_shelters(request.args.get('district'))
    return render_template('search_results.html', results=results)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)


@app.route('/api/shelter_map', methods=['GET'])
def api_shelter_map():
    """地図表示用の避難所情報を返す"""
    data = []
    for shelter in shelters:
        data.append({
            'id': shelter.get('id'),
            'name': shelter.get('name', '名称未設定'),
            'status': shelter.get('status', 'open'),
            'latitude': float(shelter.get('latitude', 40.82)),
            'longitude': float(shelter.get('longitude', 140.74)),
        })
    return jsonify({'shelters': data})

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
