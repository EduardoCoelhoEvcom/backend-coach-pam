"""O "hoje" do app é o dia no Brasil, não o UTC do servidor."""
from datetime import datetime, timezone

from services.clock import br_date_of


def test_noite_no_brasil_ainda_e_o_mesmo_dia():
    # 23h30 de 10/11 no Brasil = 02h30 de 11/11 em UTC
    utc = datetime(2026, 11, 11, 2, 30)
    assert str(br_date_of(utc)) == "2026-11-10"
    assert str(br_date_of(utc.replace(tzinfo=timezone.utc))) == "2026-11-10"
    assert str(br_date_of(datetime(2026, 11, 11, 3, 0))) == "2026-11-11"
