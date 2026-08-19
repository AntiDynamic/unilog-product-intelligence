from unilog_product_intelligence.config import GEMINI_MODEL, Settings


def test_gemini_model_is_explicit_and_stable() -> None:
    settings = Settings(_env_file=None)

    assert GEMINI_MODEL == "gemini-2.5-flash"
    assert settings.gemini_model == GEMINI_MODEL
