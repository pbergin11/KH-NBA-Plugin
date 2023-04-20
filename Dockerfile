# Use Python 3.10 image
FROM python:3.10

# Set working directory
WORKDIR /code

# Install poetry
RUN pip install poetry

# Copy pyproject.toml and poetry.lock files
COPY ./pyproject.toml ./poetry.lock* /code/

# Install dependencies using poetry
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# Copy the rest of the application code
COPY . /code/

# Start the application using uvicorn
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-${WEBSITES_PORT:-8080}}"]
