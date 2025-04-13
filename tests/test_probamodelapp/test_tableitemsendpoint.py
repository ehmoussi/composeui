from django.test import Client
from django.urls import reverse
import pytest


@pytest.fixture()
def client_with_three_rows(client: Client) -> Client:
    url = reverse("variables:api")
    # add 3 default rows
    response = client.post(url, content_type="application/json")
    assert response.status_code == 200
    response = client.post(url, content_type="application/json")
    assert response.status_code == 200
    response = client.post(url, content_type="application/json")
    assert response.status_code == 200
    return client


@pytest.mark.django_db
def test_api_get_without_row(client_with_three_rows: Client) -> None:
    url = reverse("variables:api")
    # check the get api without row
    response = client_with_three_rows.get(url)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": [
            {"row": 0, "data": ["Variable", "Normal", "1"]},
            {"row": 1, "data": ["Variable", "Normal", "2"]},
            {"row": 2, "data": ["Variable", "Normal", "3"]},
        ],
    }


@pytest.mark.django_db
def test_api_get_with_row(client_with_three_rows: Client) -> None:
    url = reverse("variables:api")
    url_row_0 = reverse("variables:api_row", args=[0])
    url_row_1 = reverse("variables:api_row", args=[1])
    url_row_2 = reverse("variables:api_row", args=[2])
    for i, url in enumerate((url_row_0, url_row_1, url_row_2)):
        rid = i + 1
        response = client_with_three_rows.get(url)
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "message": "",
            "content": {"data": ["Variable", "Normal", f"{rid}"]},
        }


@pytest.mark.django_db
def test_api_get_with_wrong_row(client_with_three_rows: Client) -> None:
    url_row_20 = reverse("variables:api_row", args=[20])
    response = client_with_three_rows.get(url_row_20)
    assert response.status_code == 400
    assert response.json() == {
        "status": "failed",
        "message": "The given row is not valid",
        "content": {"nb_rows": 3, "row": 20},
    }


@pytest.mark.django_db
def test_api_post_with_body(client: Client) -> None:
    url = reverse("variables:api")
    response = client.post(
        url, data={"0": "Test", "1": "Uniform"}, content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": {"current_row": 0, "data": ["Test", "Uniform", "1"]},
    }


@pytest.mark.django_db
def test_api_post_with_partial_wrong_body(client: Client) -> None:
    url = reverse("variables:api")
    response = client.post(
        url, data={"0": "Test", "1": "Unknown"}, content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "partial",
        "message": "The value of the column 'Distribution' have not been processed",
        "content": {"current_row": 0, "data": ["Test", "Normal", "1"]},
    }


@pytest.mark.django_db
def test_api_post_with_partial_wrong_body_2(client: Client) -> None:
    url = reverse("variables:api")
    response = client.post(
        url, data={"0": "", "1": "Unknown"}, content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "partial",
        "message": "The value of the columns ('Name', 'Distribution') have not been processed",
        "content": {"current_row": 0, "data": ["Variable", "Normal", "1"]},
    }


@pytest.mark.django_db
def test_api_post_with_wrong_body(client: Client) -> None:
    url = reverse("variables:api")
    response = client.post(
        url,
        data={"content": "Invalid content"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "partial",
        "message": "Bad content",
        "content": {"current_row": 0, "data": ["Variable", "Normal", "1"]},
    }


@pytest.mark.django_db
def test_api_post_with_row_and_body(client_with_three_rows: Client) -> None:
    url_row_1 = reverse("variables:api_row", args=[1])
    response = client_with_three_rows.post(
        url_row_1, data={"0": "Test", "1": "Uniform"}, content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": {"current_row": 1, "data": ["Test", "Uniform", "4"]},
    }


@pytest.mark.django_db
def test_api_put_with_row(client_with_three_rows: Client) -> None:
    # change name of a variable
    url_row_1 = reverse("variables:api_row", args=[1])
    response = client_with_three_rows.put(
        url_row_1, data={"0": "Test"}, content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": {"data": ["Test", "Normal", "2"]},
    }


@pytest.mark.django_db
def test_api_delete(client_with_three_rows: Client) -> None:
    # delete all
    url = reverse("variables:api")
    response = client_with_three_rows.delete(url)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": {},
    }
    # check remaining rows
    response = client_with_three_rows.get(url)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": [],
    }


@pytest.mark.django_db
def test_api_delete_row(client_with_three_rows: Client) -> None:
    # delete the second row
    url_row_1 = reverse("variables:api_row", args=[1])
    response = client_with_three_rows.delete(url_row_1)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": {"current_row": 1},
    }
    # check remaining rows
    url = reverse("variables:api")
    response = client_with_three_rows.get(url)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": [
            {"row": 0, "data": ["Variable", "Normal", "1"]},
            {"row": 1, "data": ["Variable", "Normal", "3"]},
        ],
    }


@pytest.mark.django_db
def test_api_delete_wrong_row(client_with_three_rows: Client) -> None:
    # delete an inexisting row
    url_row_1 = reverse("variables:api_row", args=[100])
    response = client_with_three_rows.delete(url_row_1)
    assert response.status_code == 400
    assert response.json() == {
        "status": "failed",
        "message": "The given row is incorrect",
        "content": {},
    }
    # check remaining rows
    url = reverse("variables:api")
    response = client_with_three_rows.get(url)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "",
        "content": [
            {"row": 0, "data": ["Variable", "Normal", "1"]},
            {"row": 1, "data": ["Variable", "Normal", "2"]},
            {"row": 2, "data": ["Variable", "Normal", "3"]},
        ],
    }
