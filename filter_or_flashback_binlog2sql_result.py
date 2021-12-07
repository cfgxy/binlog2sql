# !/usr/bin/env python3
# -*- coding:utf8 -*-

import argparse
import json
import sys
import os
import chardet
import re

# create a logger
import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def set_log_format():
    import logging.handlers
    import colorlog

    global logger

    # set logger color
    log_colors_config = {
        'DEBUG': 'bold_purple',
        'INFO': 'bold_green',
        'WARNING': 'bold_yellow',
        'ERROR': 'bold_red',
        'CRITICAL': 'bold_red',
    }

    # set logger format
    log_format = colorlog.ColoredFormatter(
        "%(log_color)s[%(asctime)s] [%(module)s:%(funcName)s] [%(lineno)d] [%(levelname)s] %(message)s",
        log_colors=log_colors_config
    )

    # add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # add rotate file handler
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(base_dir, 'logs')
    if not os.path.isdir(logs_dir):
        os.makedirs(logs_dir, exist_ok=True)

    logfile = logs_dir + os.sep + sys.argv[0].split(os.sep)[-1].split('.')[0] + '.log'
    file_maxsize = 1024 * 1024 * 100  # 100m
    # logfile_size = os.path.getsize(logfile) if os.path.exists(logfile) else 0

    file_handler = logging.handlers.RotatingFileHandler(logfile, maxBytes=file_maxsize, backupCount=10)
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)


def parse_args():
    """parse args to connect MySQL"""

    parser = argparse.ArgumentParser(description='Parse MySQL Connect Settings', add_help=False,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--help', dest='help', action='store_true', help='help information', default=False)
    parser.add_argument('--flashback', dest='flashback', action='store_true', default=False,
                        help='get flashback sql')
    parser.add_argument('--full-flashback', dest='full_flashback', action='store_true', default=False,
                        help='get full flashback sql(not filter, only work in update sql)')

    parser.add_argument('-f', '--file', dest='sql_file', type=str,
                        help='sql file you want to filter', default='')
    parser.add_argument('-p', '--pk', dest='primary_key', type=str,
                        help='choose a column to be primary key', default='`id`')
    parser.add_argument('-k', '--kcl', dest='keep_col_list', type=str, nargs='*',
                        help='choose multi column that you want to keep, these column will not be filter', default=[])
    parser.add_argument('-o', '--out-file', dest='out_file', type=str,
                        help='file that save the result', default='')
    return parser


def command_line_args(args):
    need_print_help = False if args else True
    parser = parse_args()
    args = parser.parse_args(args)
    if args.help or need_print_help:
        parser.print_help()
        sys.exit(1)

    if args.sql_file and not os.path.exists(args.sql_file):
        logger.error(f'File {args.sql_file} does not exists')
        sys.exit(1)
    elif not args.sql_file:
        logger.error('Missing sql file, we need [-f|--file] argument.')
        sys.exit(1)

    return args


def detect_file_encoding(filename):
    with open(filename, 'rb') as f:
        data = f.read()
    encoding = chardet.detect(data).get('encoding', 'unknown encoding')
    logger.info('file [' + filename + '] encoding is ' + encoding)
    return encoding


def read_file(filename, is_yield=False):
    if not os.path.exists(filename):
        print(filename + " does not exists!!!")
        sys.exit(1)

    if is_yield:
        with open(filename, 'r', encoding='utf8') as f:
            for line in f:
                yield line.strip()
    else:
        with open(filename, 'r', encoding='utf8') as f:
            info = f.readlines()
        return info


def fix_json_col(col_list):
    # 左括号数量 与 右括号数量
    json_mark_left_cnt = 0
    json_mark_right_cnt = 0
    json_col = ''
    col_list_new = []
    for i, col in enumerate(col_list):
        if isinstance(col, str):
            col = col.strip()

        if i < 3:
            col_list_new.append(col)
            continue

        if re.search('{', col) is not None:
            json_mark_left_cnt += col.count('{')
            if re.search('}', col) is not None:
                json_mark_right_cnt += col.count('}')
            json_col += col + ','
            if json_mark_left_cnt == json_mark_right_cnt:
                col_list_new.append(json_col[:-1])
                json_col = ''
            continue
        elif json_mark_left_cnt != json_mark_right_cnt:
            if re.search('}', col) is not None:
                json_mark_right_cnt += col.count('}')
            json_col += col + ','
            if json_mark_left_cnt == json_mark_right_cnt:
                col_list_new.append(json_col[:-1])
                json_col = ''
            continue
        else:
            col_list_new.append(col)
    return col_list_new


def col_list_to_dict(col_list):
    col_dict = {}
    others = []
    for col in col_list:
        if '=' in col:
            sep = '='
            col_split = col.split('`=')
            key = col_split[0] + '`'
            value = col_split[1]
        elif 'IS NULL' in col:
            sep = ' IS '
            col_split = col.split()
            key = col_split[0]
            value = col_split[-1]
        else:
            others.append(col)
            key = ''
            value = ''
            sep = ''
        key_strip = key.strip()
        if key_strip and key_strip not in col_dict:
            col_dict[key_strip] = {
                'key': key_strip,
                'sep': sep,
                'value': value.strip(),
            }
    if others:
        logger.error(others)
    return col_dict


def get_file_lines(filename):
    logger.info('getting file %s lines' % filename)
    cnt = os.popen('grep -Ev "^--|^#" %s | wc -l' % filename).read().strip('\n')
    return cnt


def filter_update(sql: str, primary_key: str = None, keep_col_list: list = None, flashback: bool = False,
                  full_flashback: bool = False) -> str:
    if not sql.strip().startswith('UPDATE'):
        return sql.strip()

    if primary_key is None:
        primary_key = '`id`'
    if keep_col_list is None:
        keep_col_list = []
    if primary_key not in keep_col_list:
        keep_col_list.append(primary_key)

    sql_split = sql.split('WHERE')
    update_col_part = sql_split[0]
    where_col_part = sql_split[1]
    begin_idx = update_col_part.find('SET')
    update_prefix = update_col_part[:begin_idx + 3]
    update_suffix = update_col_part[begin_idx + 3:]
    update_col_list = update_suffix.split(',')
    if "{" in str(update_col_list):
        update_col_list = fix_json_col(update_col_list)
    update_col_dict = col_list_to_dict(update_col_list)
    # print(json.dumps(update_col_dict, indent=4))

    where_col_list = list(map(lambda s: s.strip(), where_col_part.split(' AND ')))
    limit_idx = where_col_list[-1].find('LIMIT')
    comment_idx = where_col_list[-1].find('; #')
    comment = '; ' + where_col_list[-1][comment_idx:].strip() if comment_idx > 0 else ''
    where_col_list[-1] = where_col_list[-1][:limit_idx].strip()
    where_col_dict = col_list_to_dict(where_col_list)
    # print(json.dumps(where_col_dict, indent=4))

    update_col_list_new, where_col_list_new = [], []
    for key, new_value in update_col_dict.items():
        old_value = where_col_dict.get(key, '')
        if full_flashback:
            update_col_list_new.append('='.join([key, old_value['value']]))
            where_col_list_new.append(old_value['sep'].join([key, new_value['value']]))
            continue

        if old_value and old_value['value'] == new_value['value']:
            if key in keep_col_list:
                where_col_list_new.append(old_value['sep'].join([key, old_value['value']]))
            continue
        if old_value['value'] == 'NULL' and new_value['value'] != 'NULL':
            if flashback:
                update_col_list_new.append('='.join([key, old_value['value']]))
                where_col_list_new.append(old_value['sep'].join([key, new_value['value']]))
            else:
                update_col_list_new.append('='.join([key, new_value['value']]))
                where_col_list_new.append(old_value['sep'].join([key, old_value['value']]))
            continue
        elif old_value['value'] != 'NULL' and new_value['value'] == 'NULL':
            if flashback:
                update_col_list_new.append('='.join([key, old_value['value']]))
                where_col_list_new.append(old_value['sep'].join([key, new_value['value']]))
            else:
                update_col_list_new.append('='.join([key, new_value['value']]))
                where_col_list_new.append(old_value['sep'].join([key, old_value['value']]))
            continue

        if new_value['value'] != 'NULL' and key not in update_col_list_new:
            if flashback:
                update_col_list_new.append('='.join([key, old_value['value']]))
            else:
                update_col_list_new.append('='.join([key, new_value['value']]))
        if old_value['value'] != 'NULL' and key not in where_col_list_new:
            if flashback:
                where_col_list_new.append(old_value['sep'].join([key, new_value['value']]))
            else:
                where_col_list_new.append(old_value['sep'].join([key, old_value['value']]))

    new_sql = "".join(update_prefix) + ' ' + ','.join(update_col_list_new) + \
              ' WHERE ' + ' AND '.join(where_col_list_new) + comment
    if '; #' not in new_sql:
        new_sql += ';'
    return new_sql.strip()


def flashback_delete_sql(sql, flashback: bool = False, full_flashback: bool = False):
    if not sql.strip().upper().startswith('DELETE'):
        logger.error(f'Line {sql} is not a delete sql.')
        return sql.strip()

    if not flashback and not full_flashback:
        return sql.strip()

    from_idx = sql.find('FROM')
    where_idx = sql.find('WHERE')
    table_name = sql[from_idx + 4: where_idx]
    col_val_list = list(map(lambda s: s.strip(), sql[where_idx + 5:].split(' AND ')))
    col_val_list_last = col_val_list[-1]

    if 'LIMIT 1;' in col_val_list_last:
        col_val_list[-1] = col_val_list_last.replace('LIMIT 1', '')
        col_val_list_last = col_val_list[-1]

    comment = ''
    if '; #' in col_val_list_last:
        comment_idx = col_val_list_last.find('; #')
        comment = col_val_list_last[comment_idx + 2:]
        col_val_list[-1] = col_val_list_last[:comment_idx]

    col_part = ''
    val_part = ''
    for col_val in col_val_list:
        try:
            col, val = col_val.split('`=')
            col_part += col + '`, '
            val_part += val + ', '
        except Exception as e:
            logger.error(e)
            logger.error(f'Error sql: {sql}')
            sys.exit(1)
    else:
        col_part = col_part[:-2]
        val_part = val_part[:-2]
    new_sql = f'INSERT INTO {table_name} (' + col_part + ') VALUES (' + val_part + '); ' + comment
    return new_sql.strip()


def flashback_insert_sql(sql: str, flashback: bool = False, full_flashback: bool = False):
    if not sql.strip().upper().startswith('INSERT'):
        logger.error(f'Line {sql} is not a insert sql.')
        return sql.strip()

    if not flashback and not full_flashback:
        return sql.strip()

    sql = sql.replace('INSERT INTO', 'DELETE FROM')
    col_begin_idx = sql.find('(`')
    col_end_idx = sql.find('`)')
    val_begin_idx = sql.rfind(' VALUES (')
    val_end_idx = sql.rfind(');')
    col_list = sql[col_begin_idx + 1: col_end_idx + 1].split(', ')
    val_list = sql[val_begin_idx + 9: val_end_idx].split(', ')
    comment = ''
    if '; #' in sql:
        comment_idx = sql.find('; #')
        comment = sql[comment_idx + 2:]

    new_sql = sql[:col_begin_idx] + 'WHERE '
    for col, val in zip(col_list, val_list):
        new_sql += col + '=' + val + ' AND '
    else:
        new_sql = new_sql[:-5].strip() + '; ' + comment
    return new_sql.strip()


def filter_sql(sql, primary_key: str = None, keep_col_list: list = None, flashback: bool = False,
               full_flashback: bool = False) -> str:
    if sql.strip()[:6].upper() not in ['INSERT', 'UPDATE', 'DELETE']:
        logger.error(f'SQL [{sql}] is not a dml sql.')
        return sql

    if sql.strip().upper().startswith('UPDATE'):
        sql = filter_update(sql, primary_key, keep_col_list, flashback, full_flashback)
    elif sql.strip().upper().startswith('DELETE'):
        sql = flashback_delete_sql(sql, flashback, full_flashback)
    else:
        sql = flashback_insert_sql(sql, flashback, full_flashback)
    return sql


def main(args, sql=None):
    if sql.strip():
        new_sql = filter_sql(sql, primary_key='`id`')
        print('filter result: ', new_sql, '\n')
        new_sql = filter_sql(sql, primary_key='`id`', flashback=True)
        print('flashback result: ', new_sql, '\n')
        new_sql = filter_sql(sql, primary_key='`id`', full_flashback=True)
        print('full flashback result: ', new_sql, '\n')
        return

    sql_file = args.sql_file
    keep_col_list = args.keep_col_list
    primary_key = args.primary_key
    out_file = args.out_file
    logger.warning('This function only filter update statement')

    sql_file_len = get_file_lines(sql_file)
    cnt = 0
    info_format = '[{file}] '.format(
        file=sql_file
    )
    finished_info = info_format + 'finished'
    info_format += '[Filtered line count: {cnt} / {sql_file_len}]'

    f = open(out_file, 'w', encoding='utf8') if out_file else ''
    try:
        for line in read_file(sql_file, is_yield=True):
            if line.startswith('--') or line.startswith('#'):
                logger.warning('Ignore comment line')
                new_sql = line
            else:
                new_sql = filter_sql(line, primary_key=primary_key, keep_col_list=keep_col_list,
                                     flashback=args.flashback, full_flashback=args.full_flashback)

            if f:
                f.write(new_sql + '\n')
            else:
                print(new_sql)

            cnt += 1
            if (cnt % 10000) == 0:
                logger.info(info_format.format(cnt=cnt, sql_file_len=sql_file_len))

        logger.info(info_format.format(cnt=cnt, sql_file_len=sql_file_len))
        logger.info(finished_info)

        if out_file:
            logger.warning("The result saved in %s" % out_file)
    except Exception as e:
        logger.error('Detect error in line: [' + str(line) + '], err_msg is: ' + str(e))
    finally:
        if f:
            f.close()


if __name__ == "__main__":
    set_log_format()
    command_line_args = command_line_args(sys.argv[1:])
    test_sql = ''''''
    main(command_line_args, sql=test_sql)