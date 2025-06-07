ARG PYTHON_VERSION=3.12

FROM public.ecr.aws/lambda/python:${PYTHON_VERSION} AS builder

RUN pip install 'requests>=2,<3' --target "/asset"

FROM public.ecr.aws/lambda/python:${PYTHON_VERSION}

COPY --from=builder /asset /asset
COPY ./handlers/ /asset/app

RUN ls -l /asset/app
