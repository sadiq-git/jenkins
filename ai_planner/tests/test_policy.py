
from policy import is_allowed

def test_echo_allowed():
    assert is_allowed("echo hello")

def test_disallow_long_cmd():
    assert not is_allowed("x"*1000)

def test_python_install_allowed():
    assert is_allowed("pip install -r requirements.txt")
