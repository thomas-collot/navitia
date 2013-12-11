# encoding: utf-8

import logging

# emplacement ou charger les fichier de configuration par instances
INSTANCES_DIR = '/etc/jormungandr.d'

# chaine de connnection à postgresql pour la base jormungandr
PG_CONNECTION_STRING = 'postgresql://navitia:navitia@localhost/jormun'

# désactivation de l'authentification
PUBLIC = True

REDIS_HOST = 'localhost'

REDIS_PORT = 6379

# indice de la base de données redis utilisé, entier de 0 à 15 par défaut
REDIS_DB = 0

REDIS_PASSWORD = None

# Desactive l'utilisation du cache, et donc de redis
CACHE_DISABLED = False

# durée de vie des info d'authentification dans le cache en secondes
AUTH_CACHE_TTL = 300

ERROR_HANDLER_FILE = 'jormungandr.log'
ERROR_HANDLER_TYPE = 'rotating'  # can be timedrotating
ERROR_HANDLER_PARAMS = {'maxBytes': 20000000, 'backupCount': 5}
LOG_LEVEL = logging.DEBUG
