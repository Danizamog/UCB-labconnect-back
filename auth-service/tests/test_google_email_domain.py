import pytest

from app.application.use_cases.login_with_google import _is_in_allowed_domain


@pytest.mark.parametrize(
    ("email", "configured_domain"),
    [
        ("student@ucb.edu.bo", "@ucb.edu.bo"),
        ("  STUDENT@UCB.EDU.BO  ", "ucb.edu.bo"),
        ("student@ucb.edu.bo", " @UCB.EDU.BO "),
    ],
)
def test_google_login_accepts_exact_institutional_domain(email, configured_domain):
    assert _is_in_allowed_domain(email, configured_domain) is True


@pytest.mark.parametrize(
    "email",
    [
        "student@example.com",
        "student@ucb.edu.bo.attacker.example",
        "student@sub.ucb.edu.bo",
        "student@@ucb.edu.bo",
        "student@ucb.edu.bo@attacker.example",
        "student.ucb.edu.bo",
    ],
)
def test_google_login_rejects_non_matching_email_domains(email):
    assert _is_in_allowed_domain(email, "@ucb.edu.bo") is False
