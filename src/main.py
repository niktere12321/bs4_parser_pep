import logging
import re
from collections import defaultdict
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import (BASE_DIR, DOWNLOADS_URL, EXPECTED_STATUS, MAIN_DOC_URL,
                       PEP_URL, WHATS_NEW_URL)
from outputs import control_output
from utils import find_tag, get_response


def whats_new(session):
    """Парсер статей по нововведениям в питон."""
    response = get_response(session, WHATS_NEW_URL)
    soup = BeautifulSoup(response.text, features='lxml')
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all('li',
                                              attrs={'class': 'toctree-l1'})
    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор')]
    for section in tqdm(sections_by_python, desc='Parsing'):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(WHATS_NEW_URL, href)
        response = get_response(session, version_link)
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append((version_link, h1.text, dl_text))
    return results


def latest_versions(session):
    """Парсер текущих версий питона с описанием."""
    response = get_response(session, MAIN_DOC_URL)
    soup = BeautifulSoup(response.text, features='lxml')
    sidebar = find_tag(soup, 'div', attrs={'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        raise Exception('Ничего не нашлось')
    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        link = a_tag['href']
        re_text = re.search(pattern, a_tag.text)
        if re_text:
            version, status = re_text.groups()
        else:
            version, status = a_tag.text, ''
        results.append((link, version, status))
    return results


def download(session):
    """Парсер, скачивающий документацию."""
    response = get_response(session, DOWNLOADS_URL)
    soup = BeautifulSoup(response.text, features='lxml')
    urls_table = find_tag(soup, 'table', attrs={'class': 'docutils'})
    pdf_a4_tag = find_tag(
        urls_table, 'a', {'href': re.compile(r'.+pdf-a4\.zip$')}
    )
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(DOWNLOADS_URL, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url, verify=False)
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    """Парсер статусов PEP."""
    response = get_response(session, PEP_URL)
    result = [('Статус', 'Количество')]
    soup = BeautifulSoup(response.text, features='lxml')
    all_tables = soup.find('section', id='numerical-index')
    all_tables = all_tables.find_all('tr')
    pep_count = 0
    status_count = defaultdict(int)
    for table in tqdm(all_tables, desc='Parsing'):
        rows = table.find_all('td')
        all_status = None
        link = None
        for i, row in enumerate(rows):
            if i == 0 and len(row.text) == 2:
                all_status = row.text[1]
                continue
            if i == 1:
                link_tag = find_tag(row, 'a')
                link = link_tag['href']
                break
        link = urljoin(PEP_URL, link)
        response = get_response(session, link)
        soup = BeautifulSoup(response.text, features='lxml')
        dl = find_tag(soup, 'dl', attrs={'class': 'rfc2822 field-list simple'})
        pattern = (
                r'.*(?P<status>Active|Draft|Final|Provisional|Rejected|'
                r'Superseded|Withdrawn|Deferred|April Fool!|Accepted)'
            )
        re_text = re.search(pattern, dl.text)
        status = None
        if re_text:
            status = re_text.group('status')
        if all_status and EXPECTED_STATUS.get(all_status) != status:
            logging.info(
                f'Несовпадающие статусы:\n{link}\n'
                f'Статус в карточке: {status}\n'
                f'Ожидаемый статус: {EXPECTED_STATUS[all_status]}'
            )
        if not all_status and status not in ('Active', 'Draft'):
            logging.info(
                f'Несовпадающие статусы:\n{link}\n'
                f'Статус в карточке: {status}\n'
                f'Ожидаемые статусы: ["Active", "Draft"]'
            )
        pep_count += 1
        status_count[status] += 1
    result.extend([(status, status_count[status]) for status in status_count])
    result.append(('Total', pep_count))
    return result


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()
    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)
    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
