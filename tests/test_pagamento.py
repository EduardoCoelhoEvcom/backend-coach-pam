"""Pagamento: dia fixo, aviso de 3 dias, trava com 2 dias de atraso, Pix e comprovante."""
from datetime import date

import pytest

import routers.payments as pay
from models import AthletePlan, Payment
from services.pix import _crc16, pix_copia_e_cola

HOJE = date(2026, 12, 8)


@pytest.fixture()
def hoje(monkeypatch):
    box = {"d": HOJE}
    monkeypatch.setattr(pay, "today_br", lambda: box["d"])
    return box


@pytest.fixture()
def aluno(session, athlete_user):
    athlete_user.vencimento = date(2026, 12, 10)
    athlete_user.due_day = 10
    session.add(athlete_user)
    session.add(AthletePlan(athlete_id=athlete_user.id, plan_name="Experience", months_total=6, monthly_price=250.0))
    session.commit()
    return athlete_user


def _config(coach_client, **links):
    r = coach_client.put("/coach/payment-settings", json={
        "pix_key_type": "celular", "pix_key": "(51) 99876-5432",
        "pix_name": "Pâmela Leite", "pix_city": "Porto Alegre",
        "card_links": {"experience-3": "https://www.asaas.com/c/abc", **links},
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_proximo_vencimento_mantem_o_dia():
    assert pay.next_due(date(2026, 12, 10), 10) == date(2027, 1, 10)
    assert pay.next_due(date(2027, 1, 31), 31) == date(2027, 2, 28)
    assert pay.next_due(date(2027, 2, 28), 31) == date(2027, 3, 31)


def test_link_do_plano_com_frequencia_no_nome():
    assert pay.plan_key(AthletePlan(athlete_id=1, plan_name="Experience · 3x na semana", monthly_price=250.0)) == "experience-3"
    assert pay.plan_key(AthletePlan(athlete_id=1, plan_name="Mês avulso", monthly_price=230.0)) == "avulso-2"
    assert pay.plan_key(AthletePlan(athlete_id=1, plan_name="Time de competição", monthly_price=100.0)) == "competicao"
    assert pay.plan_key(AthletePlan(athlete_id=1, plan_name="Plano antigo", monthly_price=99.0)) is None


def test_pix_copia_e_cola():
    code = pix_copia_e_cola("+5551998765432", "Pâmela Leite", "Porto Alegre", 250)
    assert code.startswith("000201")
    assert "br.gov.bcb.pix0114+5551998765432" in code
    assert "5406250.00" in code and "5912PAMELA LEITE" in code and "6012PORTO ALEGRE" in code
    assert code[-4:] == _crc16(code[:-4])
    # exemplo conhecido do padrão CRC16-CCITT-FALSE
    assert _crc16("123456789") == "29B1"


def test_configuracao_da_coach(coach_client):
    out = _config(coach_client)
    assert out["pix_key"] == "+5551998765432"
    assert out["card_links"] == {"experience-3": "https://www.asaas.com/c/abc"}
    assert any(p["key"] == "experience-3" for p in out["plans"])
    assert out["pix_preview"].startswith("000201")
    bad = coach_client.put("/coach/payment-settings", json={"pix_key_type": "cpf", "pix_key": "123"})
    assert bad.status_code == 422
    sem_nome = coach_client.put("/coach/payment-settings", json={"pix_name": ""})
    assert sem_nome.status_code == 422


def test_estados_do_aluno(coach_client, athlete_client, aluno, hoje):
    _config(coach_client)
    hoje["d"] = date(2026, 12, 1)
    s = athlete_client.get("/athlete/payment").json()
    assert (s["state"], s["days"], s["amount"], s["locked"]) == ("em_dia", 9, 250.0, False)
    assert s["card_link"] == "https://www.asaas.com/c/abc"
    assert "5406250.00" in s["pix_code"]

    hoje["d"] = date(2026, 12, 7)
    assert athlete_client.get("/athlete/payment").json()["state"] == "vencendo"  # 3 dias antes
    hoje["d"] = date(2026, 12, 10)
    assert athlete_client.get("/athlete/payment").json()["state"] == "vencendo"  # vence hoje
    hoje["d"] = date(2026, 12, 12)
    s = athlete_client.get("/athlete/payment").json()
    assert (s["state"], s["locked"]) == ("atrasado", False)  # 2 dias: ainda aberto
    hoje["d"] = date(2026, 12, 13)
    assert athlete_client.get("/athlete/payment").json()["locked"] is True


def test_ja_paguei_libera_e_coach_confirma(coach_client, athlete_client, aluno, session, hoje):
    hoje["d"] = date(2026, 12, 14)
    assert athlete_client.get("/athlete/payment").json()["locked"] is True
    assert athlete_client.post("/athlete/payments", json={"receipt_url": ""}).status_code == 422

    r = athlete_client.post("/athlete/payments", json={"receipt_url": "https://cdn.x/receipts/1.jpg", "method": "pix"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["state"], s["locked"]) == ("em_analise", False)  # libera na hora

    ov = coach_client.get("/coach/payments").json()
    assert [p["athlete_name"] for p in ov["pending"]] == [aluno.name]
    assert ov["overdue"] == []  # quem mandou comprovante não aparece em atrasados
    pid = ov["pending"][0]["id"]

    assert coach_client.post(f"/coach/payments/{pid}/confirm").json()["status"] == "confirmado"
    session.refresh(aluno)
    assert aluno.vencimento == date(2027, 1, 10)  # mesmo dia, mês seguinte
    # confirmar de novo não anda mais um mês
    coach_client.post(f"/coach/payments/{pid}/confirm")
    session.refresh(aluno)
    assert aluno.vencimento == date(2027, 1, 10)
    assert athlete_client.get("/athlete/payment").json()["state"] == "em_dia"


def test_coach_recusa_comprovante(coach_client, athlete_client, aluno, session, hoje):
    hoje["d"] = date(2026, 12, 14)
    athlete_client.post("/athlete/payments", json={"receipt_url": "https://cdn.x/r.pdf"})
    pid = session.exec(__import__("sqlmodel").select(Payment)).first().id
    r = coach_client.post(f"/coach/payments/{pid}/reject", json={"note": "Comprovante cortado"})
    assert r.json()["status"] == "recusado"
    s = athlete_client.get("/athlete/payment").json()
    assert (s["state"], s["locked"], s["rejected_note"]) == ("atrasado", True, "Comprovante cortado")


def test_vencendo_e_atrasados_da_coach(coach_client, aluno, hoje):
    hoje["d"] = date(2026, 12, 5)
    ov = coach_client.get("/coach/payments").json()
    assert [(a["name"], a["days"]) for a in ov["due_soon"]] == [(aluno.name, 5)]
    hoje["d"] = date(2026, 12, 20)
    ov = coach_client.get("/coach/payments").json()
    assert ov["due_soon"] == [] and ov["overdue"][0]["days"] == -10 and ov["overdue"][0]["locked"]


def test_recebi_na_ficha_e_integral(coach_client, athlete_client, aluno, session, hoje):
    r = coach_client.post(f"/coach/athletes/{aluno.id}/payments", json={"method": "cartao"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["history"][0]["status"] == "confirmado" and body["status"]["due_date"] == "2027-01-10"

    # pago integral: sem aviso, sem trava, sem "Já paguei"
    coach_client.patch(f"/coach/athletes/{aluno.id}", json={"payment_mode": "integral", "vencimento": "2027-04-10"})
    hoje["d"] = date(2027, 6, 1)
    s = athlete_client.get("/athlete/payment").json()
    assert (s["state"], s["locked"], s["due_date"]) == ("integral", False, "2027-04-10")
    assert athlete_client.post("/athlete/payments", json={"receipt_url": "https://x/y.jpg"}).status_code == 400
    assert coach_client.get("/coach/payments").json()["overdue"] == []


def test_dia_do_vencimento_na_ficha(coach_client, aluno):
    coach_client.patch(f"/coach/athletes/{aluno.id}", json={"vencimento": "2026-12-15"})
    p = coach_client.get(f"/coach/athletes/{aluno.id}/profile").json()
    assert (p["vencimento"], p["due_day"]) == ("2026-12-15", 15)
    assert coach_client.patch(f"/coach/athletes/{aluno.id}", json={"due_day": 40}).status_code == 422
    assert coach_client.patch(f"/coach/athletes/{aluno.id}", json={"payment_mode": "x"}).status_code == 422
    r = coach_client.patch(f"/coach/athletes/{aluno.id}", json={"payment_link": "https://www.asaas.com/c/so-dele"})
    assert r.json()["payment_link"] == "https://www.asaas.com/c/so-dele"


def test_comprovante_upload_url(athlete_client, monkeypatch):
    import services.storage as storage

    monkeypatch.setattr(storage, "is_r2_configured", lambda: True)
    monkeypatch.setattr(storage, "presigned_put_url", lambda key, ct, expires_in=600: f"https://put/{key}")
    monkeypatch.setattr(storage, "public_url_for", lambda key: f"https://pub/{key}")
    r = athlete_client.post("/athlete/payments/receipt-upload-url", json={"content_type": "image/jpeg"})
    assert r.status_code == 200 and r.json()["public_url"].startswith("https://pub/receipts/")
    assert athlete_client.post("/athlete/payments/receipt-upload-url", json={"content_type": "video/mp4"}).status_code == 422
