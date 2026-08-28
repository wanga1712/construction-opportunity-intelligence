"""Audit expert object / form values on production (read-only)."""
from __future__ import annotations

from src.services.db_bootstrap import connect_databases


def main() -> None:
    _, _, crm, _ = connect_databases()
    fields = (
        "expert_object_type",
        "expert_object_subtype",
        "expert_work_stage",
        "expert_procurement_form",
        "expert_category_scope",
        "expert_procurement_mode",
        "expert_object_sector",
    )
    for field in fields:
        rows = crm.execute_query(
            """
            SELECT COUNT(*) AS n
            FROM crm_v3_expert_annotations
            WHERE is_current
              AND COALESCE(payload->>%s, '') <> ''
            """,
            (field,),
        )
        print(f"COUNT {field}={rows[0]['n']}")

    print("--- object types ---")
    for row in crm.execute_query(
        """
        SELECT payload->>'expert_object_type' AS v, COUNT(*) AS n
        FROM crm_v3_expert_annotations
        WHERE is_current AND COALESCE(payload->>'expert_object_type', '') <> ''
        GROUP BY 1 ORDER BY 2 DESC LIMIT 40
        """
    ):
        print(row)

    print("--- forms ---")
    for row in crm.execute_query(
        """
        SELECT payload->>'expert_procurement_form' AS v, COUNT(*) AS n
        FROM crm_v3_expert_annotations
        WHERE is_current AND COALESCE(payload->>'expert_procurement_form', '') <> ''
        GROUP BY 1 ORDER BY 2 DESC LIMIT 30
        """
    ):
        print(row)

    print("--- proposals ---")
    for row in crm.execute_query(
        """
        SELECT proposal_type, COUNT(*) AS n
        FROM crm_v3_taxonomy_proposals
        GROUP BY 1 ORDER BY 2 DESC
        """
    ):
        print(row)

    print("--- service-ish titles ---")
    rows = crm.execute_query(
        """
        SELECT COUNT(*) AS n FROM crm_procurements p
        WHERE COALESCE(p.auction_name,'') ~*
          '(техническ(ое|ого)\\s+обслуживан|содержание|обследован|сервис|эксплуатац)'
        """
    )
    print("service_title_hits_all", rows[0]["n"])
    for row in crm.execute_query(
        """
        SELECT LEFT(auction_name, 120) AS title, source_table
        FROM crm_procurements
        WHERE COALESCE(auction_name,'') ~*
          '(техническ(ое|ого)\\s+обслуживан|содержание|обследован|сервис|эксплуатац)'
        ORDER BY id DESC LIMIT 15
        """
    ):
        print(row)

    print("--- source tables ---")
    for row in crm.execute_query(
        """
        SELECT source_table, COUNT(*) AS n
        FROM crm_procurements
        GROUP BY 1 ORDER BY 2 DESC LIMIT 30
        """
    ):
        print(row)


if __name__ == "__main__":
    main()
