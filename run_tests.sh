docker run \
	--rm \
	-v $(pwd):/workspace \
	-e PYTHONPATH=/workspace:/usr/local/lib/python2.6/site-packages \
	--workdir /workspace \
	--entrypoint mayapy \
	cmdx \
	-u _runtests.py