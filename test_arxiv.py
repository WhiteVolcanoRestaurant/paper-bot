"""Legacy entry point now runs safe offline tests, never a live arXiv request."""
import unittest

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover('tests')
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
