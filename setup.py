# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import setup, find_packages

requirements = ["sockio>=0.8"]

with open("README.md") as f:
    description = f.read()


setup(
    name="gepace",
    author="Tiago Coutinho",
    author_email="tcoutinho@cells.es",
    version="0.1.0",
    description="GE Pace library",
    long_description=description,
    long_description_content_type="text/markdown",
    extras_require={
        "tango-ds": ["PyTango"],
        "simulator": ["sinstruments>=1", "scpi-protocol>=0.2"]
    },
    entry_points={
        "console_scripts": [
            "Pace = cryocon.tango:main [tango-ds]",
        ]
    },
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8"
    ],
    install_requires=requirements,
    license="LGPLv3",
    include_package_data=True,
    keywords="GE, pace, pace 5000, pace 6000, library, tango, simulator",
    packages=find_packages(),
    python_requires=">=3.5",
    url="https://github.com/ALBA-Synchrotron/gepace"
)