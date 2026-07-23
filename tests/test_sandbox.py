def test_import():
    from dbwarden_sandbox import setup
    assert callable(setup)
