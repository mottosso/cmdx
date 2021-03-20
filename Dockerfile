FROM mottosso/maya:2020

RUN wget https://bootstrap.pypa.io/pip/2.7/get-pip.py && \
  mayapy get-pip.py --user && \
  mayapy -m pip install --user \
    nose \
    nose-exclude \
    coverage \
    flaky \
    sphinx \
    sphinxcontrib-napoleon

# Avoid creation of auxilliary files
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace

ENTRYPOINT mayapy
