"""classify_import follows `raise ImportError(...) from exc` chains to the candidate's own failing import.
Run: .venv/bin/python -m unittest tests.test_eval_child_chained_import -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qbe import eval_child_v2 as child  # noqa: E402


def run(code):
    try:
        exec(compile(code, '<candidate>', 'exec'), {})
    except (ImportError, ModuleNotFoundError) as exc:
        return exc
    raise AssertionError('candidate did not raise an import error')


CHAINED = '''
def build():
    try:
        import {module}
    except ImportError as exc:
        raise ImportError("{module} is required. Install it with: python -m pip install {module}") from exc
build()
'''


class Chained(unittest.TestCase):
    def test_reraised_import_of_an_undocumented_module_is_a_candidate_failure(self):
        # The recorded astra t3_2 case: outer ImportError has no .name, inner is the real ModuleNotFoundError.
        exc = run(CHAINED.format(module='pyscf'))
        self.assertEqual(getattr(exc, 'name', None), None)
        self.assertEqual(child.classify_import(exc), ('candidate_unsupported_import', 'module_not_available', 'pyscf'))

    def test_implicit_context_chain_is_followed_too(self):
        exc = run('try:\n    import pyscf\nexcept ImportError:\n    raise ImportError("PySCF is required")\n')
        self.assertEqual(child.classify_import(exc)[0:3:2], ('candidate_unsupported_import', 'pyscf'))

    def test_reraise_of_a_missing_documented_dependency_still_aborts(self):
        # A candidate must never be able to hide a broken evaluation environment behind its own wrapper.
        child.DOCUMENTED.add('fakedoc')
        try:
            direct = run('import fakedoc')
            chained = run(CHAINED.format(module='fakedoc'))
            self.assertEqual(child.classify_import(direct), ('evaluation_environment_failure', 'documented_dependency_missing', 'fakedoc'))
            self.assertEqual(child.classify_import(chained), child.classify_import(direct))
        finally:
            child.DOCUMENTED.discard('fakedoc')

    def test_direct_and_unchained_behaviour_is_unchanged(self):
        direct = run('import definitely_not_a_module')
        self.assertEqual(child.classify_import(direct), ('candidate_unsupported_import', 'module_not_available', 'definitely_not_a_module'))
        nonexistent = run('import qiskit.optimization')
        self.assertEqual(child.classify_import(nonexistent)[0:2], ('candidate_unsupported_import', 'nonexistent_submodule'))
        bare = run('raise ImportError("something odd")')
        self.assertEqual(child.classify_import(bare), ('evaluation_environment_failure', 'unclassified_import_error', ''))

    def test_chain_that_does_not_start_in_the_candidate_is_not_followed(self):
        # inner failure raised inside library code, not '<candidate>' => not treated as the candidate's import
        namespace = {}
        exec(compile('def lib():\n    import pyscf_in_lib\n', 'library.py', 'exec'), namespace)
        try:
            exec(compile('try:\n    lib()\nexcept ImportError as e:\n    raise ImportError("wrapped") from e\n', '<candidate>', 'exec'), namespace)
        except ImportError as exc:
            self.assertEqual(child.underlying_candidate_import_error(exc), exc)


if __name__ == '__main__':
    unittest.main()
