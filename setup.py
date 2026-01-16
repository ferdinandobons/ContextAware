from setuptools import setup, find_packages

setup(
    name="context_aware",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.0.0",
    ],
    entry_points={
        "console_scripts": [
            "context_aware=context_aware.cli.main:main",
        ],
    },
)
