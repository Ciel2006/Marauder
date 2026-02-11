from setuptools import setup, find_packages
from marauder import __version__

setup(
    name="marauder-code",
    version=__version__,
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "rich>=13.0.0",
        "prompt_toolkit>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "marauder=marauder.cli:main",
            "Marauder=marauder.cli:main",
        ],
    },
    python_requires=">=3.10",
)
