import pytest

from dnd5e import escape_hatch


@pytest.fixture(autouse=True)
def _clear_cache():
    escape_hatch.clear_cache()
    yield
    escape_hatch.clear_cache()


def test_resolve_imports_module_and_instantiates_class():
    instance = escape_hatch.resolve("python:collections.OrderedDict")
    assert type(instance).__name__ == "OrderedDict"


def test_resolve_caches_by_handler_string():
    a = escape_hatch.resolve("python:collections.OrderedDict")
    b = escape_hatch.resolve("python:collections.OrderedDict")
    assert a is b


def test_resolve_rejects_non_python_prefix():
    with pytest.raises(ValueError, match="must start with 'python:'"):
        escape_hatch.resolve("collections.OrderedDict")


def test_resolve_rejects_missing_class_name():
    with pytest.raises(ValueError, match="expected 'module.ClassName'"):
        escape_hatch.resolve("python:collections")


def test_resolve_propagates_import_error_for_unknown_module():
    with pytest.raises(ModuleNotFoundError):
        escape_hatch.resolve("python:no_such_module_xyz.Brain")


def test_clear_cache_forces_a_fresh_instance():
    a = escape_hatch.resolve("python:collections.OrderedDict")
    escape_hatch.clear_cache()
    b = escape_hatch.resolve("python:collections.OrderedDict")
    assert a is not b
