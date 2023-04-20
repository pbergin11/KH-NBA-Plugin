# Use Python 3.10 image
FROM python:3.10

# Set working directory
WORKDIR /code

# Copy requirements.txt file
COPY ./requirements.txt /code/

# Install dependencies using pip
RUN pip install -r requirements.txt

# Copy the rest of the application code
COPY . /code/

# Start the application using uvicorn
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-${WEBSITES_PORT:-8080}}"]
