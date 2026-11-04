from ui.dashboards import about_dashboard, my_bookings_dashboard
from core.config import settings


def test_demo_description_is_neutral_and_escaped(monkeypatch):
    monkeypatch.setattr(settings, 'salon', {
        'name': 'Nail Atelier',
        'tagline': 'Студия маникюра и ухода',
        'description': 'Демо <студия>',
    })
    text = about_dashboard()
    assert 'Демо &lt;студия&gt;' in text
    assert 'СанПиН' not in text
    assert 'Гарантия на покрытие' not in text


def test_empty_bookings_do_not_contain_customer_information():
    text = my_bookings_dashboard([])
    assert 'Активных записей не найдено' in text
    assert 'Запись #' not in text
