# Cockpit granulés — Hympyr Énergies

Simulateur Streamlit de prix HT/TTC et livraison, grille tarifaire éditable et analyse de l'historique des prix.

## Activer la persistance Supabase

La table `public.granules_state` et la fonction `public.granules_save_state` ont été installées dans le projet **cmvkijtlkzfwnzipgstc**. Le schéma de référence figure dans `supabase/granules.sql` ; ne pas réexécuter ce fichier sur un projet où les objets existent déjà.

Dans **Streamlit Community Cloud → votre application → Settings → Secrets**, ajouter les trois valeurs de `.streamlit/secrets.toml.example` :

```toml
SUPABASE_URL = "https://cmvkijtlkzfwnzipgstc.supabase.co"
SUPABASE_SECRET_KEY = "REMPLACER_PAR_VOTRE_CLE_SERVEUR_sb_secret"
GRANULES_APP_PASSWORD = "REMPLACER_PAR_UN_MOT_DE_PASSE_LONG_ET_UNIQUE"
```

La clé serveur se trouve dans **Supabase → projet → Settings → API Keys → Secret keys**. Une ancienne clé `service_role` reste compatible via `SUPABASE_SERVICE_ROLE_KEY`. Une clé `anon` ou `sb_publishable_` n'a volontairement aucun accès à ces données. Ne jamais publier la clé serveur dans GitHub, dans un formulaire de l'application ou dans une conversation. Le mot de passe d'équipe doit contenir au moins 16 caractères et être partagé par un canal interne adapté.

Enregistrer les secrets, puis ouvrir l'application et se connecter avec le mot de passe d'équipe. La première fois, importer le classeur de référence depuis « Grille tarifaire », ou vérifier les valeurs par défaut et cliquer sur **Enregistrer l'état actuel**. La base est initialement vide : aucun ancien contenu de session Streamlit n'a été récupéré automatiquement. Exporter d'abord en Excel les données d'une ancienne session encore ouverte avant un redémarrage.

## Comportement

- Au début de chaque session connectée, la grille et l'historique sont rechargés depuis Supabase.
- Chaque validation de grille, import, ajout concurrent, archivage et suppression de l'historique sauvegarde l'état complet en une transaction atomique.
- Les modifications d'un collègue ne se chargent pas en temps réel : utiliser **Recharger depuis la base**. Une case confirme l'abandon du travail local.
- Deux sessions ne peuvent pas écraser silencieusement leurs changements : une révision périmée provoque un conflit. Exporter le travail local, recharger la base, puis réappliquer les modifications nécessaires.
- Une panne d'écriture affiche une erreur et conserve les données en session. Une sauvegarde dont le résultat est incertain exige une vérification par rechargement, après export du travail local.
- Une base configurée mais inaccessible bloque le démarrage du simulateur pour éviter des calculs avec des tarifs par défaut.
- Sans configuration Supabase, le mode historique « session seule » reste accessible avec un avertissement explicite. Aucune sauvegarde distante n'est alors effectuée.

## Sécurité et limites

Les requêtes REST sont effectuées par Python côté serveur, via `requests`, avec des délais limites et sans redirections. Aucun nouveau SDK n'est requis. Les prix HT/TTC sont conservés tels que validés, sans recalcul au chargement.

La table a RLS activé et les droits des rôles publics révoqués. Seul le rôle serveur peut lire et appeler la fonction de sauvegarde, qui s'exécute avec les droits de l'appelant. L'absence de politique publique est intentionnelle. La clé serveur du projet est privilégiée : elle doit rester exclusivement dans les secrets Streamlit. L'accès à l'application est commun à l'équipe ; il ne fournit pas d'identification individuelle ni de journal par utilisateur. La suppression d'historique est partagée et n'offre pas de corbeille : exporter le classeur avant suppression.

L'état métier est un document JSON versionné unique : cette solution convient à l'usage interne de ce cockpit. Pour de très grands historiques ou des analyses SQL ligne par ligne, prévoir une évolution vers des tables normalisées.

## Développement et validation

```bash
python -m pip install -r requirements.txt
python -m streamlit run app_gran.py
```

Pour la configuration locale, copier `.streamlit/secrets.toml.example` vers `.streamlit/secrets.toml` (ignoré par Git) et renseigner les valeurs. Les variables d'environnement de même nom sont également prises en charge.

```bash
python -m pip install pytest
python -m pytest -q
```

Les tests vérifient la sérialisation, les dates et montants, la protection avant accès à la base, la sauvegarde/relecture entre sessions, les conflits et la conservation du travail en cas d'erreur. Les tests d'application utilisent une base simulée ; les droits SQL et la fonction ont également été vérifiés sur le projet Supabase dans une transaction annulée.
