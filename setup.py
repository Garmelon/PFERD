from setuptools import find_packages, setup

setup(
    name="PFERD",
    version="1.1.8",
    packages=find_packages(),
    install_requires=[
        "requests>=2.21.0",
        "beautifulsoup4>=4.7.1",
        "rich>=1.0.0"
    ],
)

# When updating the version, also:
# - update the README.md installation instructions
# - set a tag on the update commit
