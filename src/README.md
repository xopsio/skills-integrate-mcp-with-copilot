# Mergington High School Activities API

A FastAPI application that lets students view and sign up for extracurricular activities at Mergington High School. Activity data is persisted to a relational database through SQLAlchemy; the current implementation uses SQLite by default for local development.

## Features

- View all available extracurricular activities
- Sign up for activities
- Unregister from activities

## Getting Started (clean checkout)

From the repository root:

1. Install the dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Apply the database migrations:

   ```
   alembic upgrade head
   ```

3. Load the demo seed data:

   ```
   python -m src.seed
   ```

4. Run the API:

   ```
   uvicorn src.app:app --reload
   ```

5. Open in your browser:

   - Application: http://localhost:8000/
   - API documentation: http://localhost:8000/docs
   - Alternative documentation: http://localhost:8000/redoc

## Database Configuration

- Data is persisted through SQLAlchemy; the application does not store activity data in memory.
- The default local database is SQLite; the file is `mergington.db` at the repository root.
- The connection URL is taken from the `DATABASE_URL` environment variable. When unset, SQLite is used.
- Migrations must be applied (`alembic upgrade head`) before serving requests; the application does not run migrations at startup.
- Seed data is loaded with `python -m src.seed`; the application does not seed at startup.

## API Endpoints

| Method | Endpoint                                                          | Description                                       |
| ------ | ----------------------------------------------------------------- | ------------------------------------------------- |
| GET    | `/activities`                                                     | List activities with their current participants   |
| POST   | `/activities/{activity_name}/signup?email=student@mergington.edu` | Sign up the given email for the named activity    |
| DELETE | `/activities/{activity_name}/unregister?email=student@mergington.edu` | Unregister the given email from the named activity |

Responses preserve the existing API contract:

- `GET /activities` returns a dictionary keyed by activity name. Each value contains `description`, `schedule`, `max_participants`, and `participants` (a list of email strings, no database IDs).
- `POST .../signup` returns `{"message": "Signed up <email> for <activity>"}` on success, `404 Activity not found` for unknown activity, and `400 Student is already signed up` for duplicate signups.
- `DELETE .../unregister` returns `{"message": "Unregistered <email> from <activity>"}` on success, `404 Activity not found` for unknown activity, and `400 Student is not signed up for this activity` if the user is unknown or has no matching registration.

Signups are not rejected when an activity reaches `max_participants`; the current backend does not enforce capacity.

## Data Model

The schema is managed by SQLAlchemy and Alembic. The current models are:

- **User** — `id`, `email` (unique)
- **Activity** — `id`, `name` (unique), `description`, `schedule`, `max_participants`
- **Registration** — `id`, `user_id` (FK to users), `activity_id` (FK to activities), with a `UNIQUE(user_id, activity_id)` constraint and `ON DELETE RESTRICT` on both foreign keys

The application treats students as identified by their email. The data model described for the original implementation also lists the following student fields:

- Name
- Grade level

The discrepancy between the described student fields and the current `User` model is intentionally preserved for the maintainer to resolve.
