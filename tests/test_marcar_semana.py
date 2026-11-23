"""Coach marca como feita uma semana que já passou (e pode desfazer)."""
from datetime import timedelta

from sqlmodel import select

from models import TrainingDayCompletion, TrainingSetExecution, TrainingSheet
from services.clock import today_br


def _plano():
    def dia(day, rest=False):
        if rest:
            return {"day": day, "rest": True, "technical": [], "lpo_exercises": [], "accessories": []}
        return {
            "day": day,
            "rest": False,
            "technical": [{"name": "Mobilidade: Quadril"}],
            "lpo_exercises": [{
                "name": "Snatch Teste", "exercise_id": 1, "is_complex": False,
                "series": [{"reps": 3, "percent": 70}, {"reps": 3, "percent": 75}],
            }],
            "accessories": [{"name": "Remada", "series": [{"reps": 10}]}],
        }
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return {"weeks": [
        {"week_number": n, "days": [dia(d, d not in ("monday", "friday")) for d in days]} for n in (1, 2, 3)
    ]}


def _planilha(session, coach_user, athlete_user, weeks_ago=2):
    today = today_br()
    monday = today - timedelta(days=today.weekday()) - timedelta(days=7 * weeks_ago)
    sheet = TrainingSheet(
        athlete_id=athlete_user.id, coach_id=coach_user.id, title="Ciclo", weeks=3, same_weeks=False,
        plan=_plano(), start_date=monday, end_date=monday + timedelta(days=20),
    )
    session.add(sheet)
    session.commit()
    session.refresh(sheet)
    return sheet


def _execs(session, sheet_id, week):
    session.expire_all()
    return session.exec(select(TrainingSetExecution).where(
        TrainingSetExecution.training_sheet_id == sheet_id, TrainingSetExecution.week_number == week,
    )).all()


def test_marca_semana_e_datas(coach_client, session, coach_user, athlete_user):
    sheet = _planilha(session, coach_user, athlete_user)
    r = coach_client.post(f"/coach/training-sheets/{sheet.id}/weeks/1/mark-done")
    assert r.status_code == 200, r.text
    assert (r.json()["days"], r.json()["marked"]) == (2, 8)  # 2 dias x (1 mobilidade + 2 séries + 1 acessório)
    rows = _execs(session, sheet.id, 1)
    assert len(rows) == 8 and all(x.status == "fez" and x.marked_by_coach for x in rows)
    assert {x.date_completed for x in rows} == {sheet.start_date, sheet.start_date + timedelta(days=4)}
    assert len(session.exec(select(TrainingDayCompletion).where(TrainingDayCompletion.training_sheet_id == sheet.id)).all()) == 2
    # repetir não duplica
    assert coach_client.post(f"/coach/training-sheets/{sheet.id}/weeks/1/mark-done").json()["marked"] == 0
    assert len(_execs(session, sheet.id, 1)) == 8
    listed = coach_client.get(f"/coach/training-sheets/{sheet.id}/executions").json()
    assert all(x["marked_by_coach"] for x in listed)


def test_nao_mexe_no_que_o_atleta_marcou(coach_client, session, coach_user, athlete_user):
    sheet = _planilha(session, coach_user, athlete_user)
    session.add(TrainingSetExecution(
        athlete_id=athlete_user.id, training_sheet_id=sheet.id, week_number=1, day="monday",
        date_completed=sheet.start_date, exercise_name="Snatch Teste", series_index=0, status="errou", note="perdi",
    ))
    session.add(TrainingSetExecution(
        athlete_id=athlete_user.id, training_sheet_id=sheet.id, week_number=1, day="monday",
        date_completed=sheet.start_date, exercise_name="Snatch Teste", series_index=1, status=None, used_kg=50,
    ))
    session.commit()
    assert coach_client.post(f"/coach/training-sheets/{sheet.id}/weeks/1/mark-done").json()["marked"] == 7
    rows = _execs(session, sheet.id, 1)
    assert len(rows) == 8
    real = next(x for x in rows if x.series_index == 0 and x.exercise_name == "Snatch Teste" and x.day == "monday")
    assert real.status == "errou" and not real.marked_by_coach
    # desfazer tira só o da coach, e mantém a carga que o atleta anotou
    assert coach_client.delete(f"/coach/training-sheets/{sheet.id}/weeks/1/mark-done").json()["removed"] == 7
    rows = _execs(session, sheet.id, 1)
    assert len(rows) == 2 and {x.status for x in rows} == {"errou", None}
    assert next(x for x in rows if x.series_index == 1).used_kg == 50


def test_desfazer_limpa_conclusao(coach_client, session, coach_user, athlete_user):
    sheet = _planilha(session, coach_user, athlete_user)
    coach_client.post(f"/coach/training-sheets/{sheet.id}/weeks/2/mark-done")
    assert coach_client.delete(f"/coach/training-sheets/{sheet.id}/weeks/2/mark-done").json()["removed"] == 8
    assert _execs(session, sheet.id, 2) == []
    assert session.exec(select(TrainingDayCompletion).where(TrainingDayCompletion.training_sheet_id == sheet.id)).all() == []


def test_so_semana_que_ja_terminou(coach_client, session, coach_user, athlete_user):
    sheet = _planilha(session, coach_user, athlete_user)
    assert coach_client.post(f"/coach/training-sheets/{sheet.id}/weeks/3/mark-done").status_code == 400
    assert coach_client.post(f"/coach/training-sheets/{sheet.id}/weeks/9/mark-done").status_code == 404
    assert _execs(session, sheet.id, 3) == []


def test_atleta_nao_pode_marcar(athlete_client, session, coach_user, athlete_user):
    sheet = _planilha(session, coach_user, athlete_user)
    assert athlete_client.post(f"/coach/training-sheets/{sheet.id}/weeks/1/mark-done").status_code == 403
