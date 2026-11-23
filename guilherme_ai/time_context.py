import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


SAO_PAULO = ZoneInfo("America/Sao_Paulo")
_WEEKDAYS = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}
_NUMBER_WORDS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
}


def current_datetime_context(now: datetime | None = None) -> str:
    current = now or datetime.now(SAO_PAULO)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SAO_PAULO)
    else:
        current = current.astimezone(SAO_PAULO)
    return f"{current.isoformat(timespec='minutes')} [America/Sao_Paulo]"


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(character for character in decomposed if unicodedata.category(character) != "Mn")


def _format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def resolve_relative_dates(
    text: str,
    now: datetime | None = None,
) -> tuple[str, ...]:
    current = now or datetime.now(SAO_PAULO)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SAO_PAULO)
    else:
        current = current.astimezone(SAO_PAULO)
    today = current.date()
    normalized = _normalize(text)
    resolutions: list[str] = []

    relative_days = (
        (r"\banteontem\b", 2, "Anteontem"),
        (r"\bontem\b", 1, "Ontem"),
        (r"\bhoje\b", 0, "Hoje"),
    )
    for pattern, days_ago, label in relative_days:
        if re.search(pattern, normalized):
            resolutions.append(f"{label} = {_format_date(today - timedelta(days=days_ago))}")

    if re.search(r"\bsemana passada\b", normalized):
        current_monday = today - timedelta(days=today.weekday())
        start = current_monday - timedelta(days=7)
        end = current_monday - timedelta(days=1)
        resolutions.append(
            f"Semana passada = {_format_date(start)} a {_format_date(end)}"
        )

    if re.search(r"\bmes passado\b", normalized):
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        resolutions.append(
            f"Mês passado = {_format_date(last_month_start)} a "
            f"{_format_date(last_month_end)}"
        )

    days_match = re.search(
        r"\bultimos?\s+(?P<count>\d{1,2}|[a-z]+)\s+dias?\b",
        normalized,
    )
    if days_match:
        count_text = days_match.group("count")
        count = int(count_text) if count_text.isdigit() else _NUMBER_WORDS.get(count_text)
        if count is not None and 1 <= count <= 31:
            start = today - timedelta(days=count - 1)
            resolutions.append(
                f"Últimos {count} dias = {_format_date(start)} a {_format_date(today)}"
            )

    weekday_pattern = re.compile(
        r"\b(?P<weekday>segunda|terca|quarta|quinta|sexta|sabado|domingo)"
        r"(?:[\s-]+feira)?\b"
    )
    for match in weekday_pattern.finditer(normalized):
        context = normalized[max(0, match.start() - 18):match.end() + 18]
        weekday = _WEEKDAYS[match.group("weekday")]
        delta = (today.weekday() - weekday) % 7
        if "proxima" in context or "que vem" in context:
            delta = (weekday - today.weekday()) % 7 or 7
            target = today + timedelta(days=delta)
            label = f"Próxima {match.group('weekday')}-feira"
        else:
            if delta == 0 and ("passad" in context or "ultima" in context):
                delta = 7
            target = today - timedelta(days=delta)
            label = f"{match.group('weekday').capitalize()} considerada"
        resolutions.append(f"{label} = {_format_date(target)}")

    explicit_date_pattern = re.compile(r"\b(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>\d{4})\b")
    for match in explicit_date_pattern.finditer(normalized):
        try:
            explicit = date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
        if explicit > today:
            status = "futura"
        elif explicit < today:
            status = "passada"
        else:
            status = "hoje"
        resolutions.append(
            f"Data explícita {_format_date(explicit)} = {status} em relação a "
            f"{_format_date(today)}"
        )

    return tuple(dict.fromkeys(resolutions))[:5]
