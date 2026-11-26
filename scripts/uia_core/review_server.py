"""A temporary, single-run review workbench bound to the local machine."""

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import review_page, workflow
from .common import RunBusy, UiaError, load_run, locked_run, require, save


def serve(run, emit):
    path, manifest = load_run(run)
    require(not workflow.historical_intent_run(path.parent, manifest), '历史 Intent 运行仅供查看')
    require(manifest['cases'], '当前运行没有可审核的用例')
    run_id = manifest['run_id']
    page_path = '/review/' + secrets.token_urlsafe(24)
    submit_path = page_path + '/submit'

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_args):
            # The URL contains a session secret. Only the startup receipt prints it.
            pass

        def reply(self, status, content, content_type='application/json; charset=utf-8'):
            body = (content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)).encode('utf-8')
            try:
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Frame-Options', 'DENY')
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionError, TimeoutError):
                pass

        def error(self, status, code, message):
            self.reply(status, {'ok': False, 'code': code, 'message': message})

        def is_session_route(self, expected):
            if self.headers.get('Host') != authority or self.path != expected:
                self.error(HTTPStatus.NOT_FOUND, 'not_found', '审核链接已失效。')
                return False
            return True

        def do_GET(self):
            if not self.is_session_route(page_path):
                return
            try:
                _, current = load_run(path)
                require(current['run_id'] == run_id and not workflow.historical_intent_run(path.parent, current), '审核运行已变化。')
                html, _ = review_page.render_html(path.parent, current, submit_url=submit_path)
            except (UiaError, OSError, ValueError):
                self.error(HTTPStatus.CONFLICT, 'review_unavailable', '无法读取当前审核材料，请稍后刷新。')
                return
            self.reply(HTTPStatus.OK, html, 'text/html; charset=utf-8')

        def do_POST(self):
            if not self.is_session_route(submit_path):
                return
            if self.headers.get('Origin') != origin:
                self.error(HTTPStatus.FORBIDDEN, 'wrong_origin', '请从本次审核页面提交。')
                return
            if self.headers.get_content_type() != 'application/json':
                self.error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, 'bad_request', '审核结果格式不正确。')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024 * 1024:
                    self.error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, 'bad_request', '审核结果为空或超过提交大小限制。')
                    return
                document = json.loads(self.rfile.read(length).decode('utf-8'))
            except (ValueError, TimeoutError):
                self.error(HTTPStatus.BAD_REQUEST, 'bad_request', '审核结果读取不完整，请重试。')
                return
            if not isinstance(document, dict) or not isinstance(document.get('review_state'), str):
                self.error(HTTPStatus.BAD_REQUEST, 'bad_request', '审核结果缺少页面版本，请刷新后重试。')
                return
            try:
                with locked_run(path, timeout=0) as (_, current):
                    require(current['run_id'] == run_id and not workflow.historical_intent_run(path.parent, current), '审核运行已变化。')
                    if current.get('active_batch'):
                        raise RunBusy('测试批次正在运行。')
                    result = review_page.ingest_payload(path.parent, current, document, expected_state=document['review_state'])
                    if not result['already_saved']:
                        save(path, current)
                    receipt = {'run_id': run_id, 'review_state': review_page.review_state(current),
                               'decisions': result['decisions'], 'pending': result['pending'],
                               'already_saved': result['already_saved'], 'next': result['next']}
            except RunBusy:
                self.error(HTTPStatus.CONFLICT, 'run_busy', '当前运行正在处理其他操作。请稍后重试，草稿已保留。')
                return
            except review_page.ReviewConflict as error:
                self.error(HTTPStatus.CONFLICT, 'review_conflict', str(error))
                return
            except UiaError as error:
                self.error(HTTPStatus.BAD_REQUEST, 'invalid_review', str(error))
                return
            except (OSError, ValueError):
                self.error(HTTPStatus.SERVICE_UNAVAILABLE, 'save_failed', '暂时无法保存审核结果，请重试。')
                return
            if not receipt['already_saved']:
                emit({'event': 'review_saved', 'run_id': run_id, 'decisions': len(receipt['decisions']),
                      'pending': len(receipt['pending']), 'next': receipt['next']})
            self.reply(HTTPStatus.OK, {'ok': True, **receipt})

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        authority = f'127.0.0.1:{server.server_port}'
        origin = 'http://' + authority
        emit({'event': 'review_ready', 'run_id': run_id, 'url': origin + page_path})
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return {'event': 'review_stopped', 'run_id': run_id}
