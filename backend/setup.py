#!/usr/bin/env python3
"""
Setup configuration for Bill of Entry Extractor
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

# Read requirements
requirements_file = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_file.exists():
    requirements = [
        line.strip()
        for line in requirements_file.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="bill-of-entry-extractor",
    version="2.0.0",
    description="Extract structured data from Indian Customs Bills of Entry and Shipping Bills using Gemini Vision API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Your Name",
    author_email="your.email@example.com",
    url="https://github.com/yourusername/Gemini-ip-customs",

    # Package configuration
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.11",

    # Dependencies
    install_requires=requirements,

    # Optional dependencies
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
        ],
    },

    # Entry points for command-line scripts
    entry_points={
        "console_scripts": [
            "extract-bill=bill_of_entry_extractor.main:main",
            "extract-shipping-bill=bill_of_entry_extractor.shipping_bill_main:main",
        ],
    },

    # Classifiers
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],

    # Include package data (schemas, etc.)
    include_package_data=True,
    package_data={
        "": ["*.json"],
    },
)
