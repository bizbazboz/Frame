import os

os.environ.setdefault('SECRET_KEY', 'test-only-secret')
os.environ['OIDC_ALLOWED_SUBJECTS'] = 'allowed'
os.environ['OIDC_ISSUER'] = 'https://oidc.example.test'
os.environ['OIDC_CLIENT_ID'] = 'test-client'
os.environ['OIDC_CLIENT_SECRET'] = 'test-only-client-secret'
