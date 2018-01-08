FROM mottosso/maya:2017

RUN wget https://bootstrap.pypa.io/get-pip.py && \
	mayapy get-pip.py && \
	mayapy -m pip install \
		nose \
		nose-exclude \
		coverage \
		sphinx \
		six \
		sphinxcontrib-napoleon \
		python-coveralls

# Avoid creation of auxilliary files
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace

ENTRYPOINT mayapy
