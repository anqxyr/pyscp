import pathlib
import setuptools

with open(str(pathlib.Path(__file__).resolve().parent / 'README.md')) as f:
    readme = f.read()

setuptools.setup(
    name='pyscp',
    version='0.8.2',
    description='Python API and utilities for the scp-wiki.net website.',
    long_description=readme,
    url='https://github.com/anqxyr/pyscp/',
    author='anqxyr',
    author_email='anqxyr@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Other Audience',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.4'],
    packages=['pyscp'],
    install_requires=[
        'arrow',
        'beautifulsoup4',
        'cached_property',
        'requests',
        'peewee'],
)
