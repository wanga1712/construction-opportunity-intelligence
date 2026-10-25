CREATE TABLE IF NOT EXISTS public.category_discovery_config (
    scope_key                  text PRIMARY KEY,
    min_distinct_procurements  integer NOT NULL DEFAULT 10,
    min_occurrences            integer NOT NULL DEFAULT 20,
    min_supply_value_rub       numeric NOT NULL DEFAULT 0,
    okpd_cluster_digits        integer NOT NULL DEFAULT 4,
    default_medal              text NOT NULL DEFAULT 'WOOD',
    enabled                    boolean NOT NULL DEFAULT true,
    updated_at                 timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.category_discovery_config (scope_key)
VALUES ('DEFAULT')
ON CONFLICT (scope_key) DO NOTHING;
