from fastapi.testclient import TestClient
from bs4 import BeautifulSoup
from src.main import create_app


def test_input_and_queue_are_independent_pages(tmp_path):
    app = create_app(tmp_path / 'pages.sqlite')
    with TestClient(app) as client:
        home = BeautifulSoup(client.get('/').text, 'html.parser')
        assert home.select_one('#case-form') is None
        new = client.get('/new')
        assert new.status_code == 200
        form = BeautifulSoup(new.text, 'html.parser')
        assert form.select_one('#case-form') is not None
        assert form.select_one('#cases') is None
        queue = client.get('/investigations')
        assert queue.status_code == 200
        listing = BeautifulSoup(queue.text, 'html.parser')
        assert listing.select_one('#case-filter') is not None
        assert listing.select_one('#case-form') is None


def test_case_detail_is_reloadable_and_belongs_to_its_stored_batch(tmp_path):
    app = create_app(tmp_path / 'detail.sqlite')
    with TestClient(app) as client:
        store = app.state.store
        bid, _ = store.create_batch({'idempotency_key':'page-routing','mode':'sample','cases':[{'sku':'<unsafe>'}]})
        cid = store.batch(bid)[0]['id']
        response = client.get(f'/cases/{cid}?batch=untrusted')
        assert response.status_code == 200
        doc = BeautifulSoup(response.text, 'html.parser')
        assert doc.body['data-case-id'] == cid
        assert doc.body['data-batch-id'] == bid
        assert doc.select_one('#back-to-queue')['href'] == f'/investigations?batch={bid}'
        assert '<unsafe>' not in response.text
        assert doc.select_one('#case-form') is None
        assert client.get('/cases/missing').status_code == 404
