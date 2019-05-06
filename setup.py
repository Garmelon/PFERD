from setuptools import setup

setup(
        name="PFERD",
        version="1.1.1",
        packages=["PFERD"],
        install_requires=[
            "requests>=2.21.0",
            "beautifulsoup4>=4.7.1",
        ],
)

# When updating the version, also:
# - update the README.md installation instructions
# - set a tag on the update commit
