from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases

def main():
    _, _, crm_db, _ = connect_databases()
    if crm_db:
        print("CATEGORIES MATCHING 43.21%:")
        cats = crm_db.execute_query("SELECT category_code, category_name, is_active FROM crm_product_categories WHERE category_code LIKE '43.21%'")
        for c in cats:
            print(c)

if __name__ == '__main__':
    main()
