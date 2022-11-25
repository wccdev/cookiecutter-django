### Source: https://simpleisbetterthancomplex.com/tutorial/2016/07/26/how-to-reset-migrations.html

# Delete migrations
find -E . -regex "{{cookiecutter.project_slug}}/(?!crontrib/|users/)[^/]+?/migrations/(?!__init__\.py).+\.(py|pyc)" -delete

# Drop database
# (delete db.sqlite3 or see https://stackoverflow.com/questions/34576004/simple-way-to-reset-django-postgresql-database

# Create migrations and generate DB schema
./manage.py makemigrations
#./manage.py migrate --fake
