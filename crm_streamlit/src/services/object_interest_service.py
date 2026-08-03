"""Ручная отметка «не интересно» — tender_document_matches + crm_objects_index."""

from __future__ import annotations



from typing import Tuple



from loguru import logger

from psycopg2.extras import RealDictCursor





def _set_matches_not_interesting(

    tender_db,

    tender_id: int,

    registry_type: str,

) -> Tuple[bool, str]:

    """

    Пометить совпадения закупки как неинтересные.



    MatchStatusService из десктопа вызывает execute_query() для UPDATE без RETURNING —

    fetchall() возвращает пустой список, и статус ошибочно считается неуспешным.

    """

    if not tender_db or tender_db.is_offline_mode():

        return False, "База tender_monitor недоступна"



    try:

        if not tender_db.is_connected():

            tender_db.connect()

        conn = tender_db.get_connection()

        if not conn:

            return False, "Нет соединения с tender_monitor"



        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            cur.execute(

                """

                UPDATE tender_document_matches

                SET is_interesting = FALSE, updated_at = NOW()

                WHERE tender_id = %s AND registry_type = %s

                RETURNING id

                """,

                (tender_id, registry_type),

            )

            rows = cur.fetchall()



        if rows:

            logger.info(

                f"Снят интерес: tender_id={tender_id}, "

                f"registry_type={registry_type}, rows={len(rows)}"

            )

            return True, ""



        return False, "Записи совпадений не найдены в БД для этой закупки"



    except Exception as exc:

        logger.error(f"_set_matches_not_interesting: {exc}")

        return False, f"Ошибка БД: {exc}"





def mark_object_not_interesting(

    *,

    tender_db,

    crm_db,

    tender_id: int,

    registry_type: str,

    object_key: str,

    objects_service=None,

) -> Tuple[bool, str]:

    """Скрыть объект: is_interesting=FALSE в tender_monitor, удалить из индекса CRM."""

    if not tender_db:

        return False, "Нет подключения к tender_monitor"



    ok, err = _set_matches_not_interesting(tender_db, tender_id, registry_type)

    if not ok:

        return False, err or "Не удалось обновить статус совпадений в БД"



    if crm_db and not crm_db.is_offline_mode():

        try:

            crm_db.execute_update(

                "DELETE FROM crm_objects_index WHERE object_key = %s",

                (object_key,),

            )

        except Exception as exc:

            logger.warning(f"crm_objects_index delete: {exc}")



    if objects_service is not None:

        objects_service.remove_item_by_key(object_key)



    return True, "Объект отмечен как неинтересный и убран из списка"

