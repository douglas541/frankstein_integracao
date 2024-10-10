data = {
  "series": {
    "Série 6000": {
      "modelos": [
        {
          "nome": "6110J",
          "referencia": "manualOperador_6110j_6125j_6130j.pdf"
        },
        {
          "nome": "6125J",
          "referencia": "manualOperador_6110j_6125j_6130j.pdf"
        },
        {
          "nome": "6130J",
          "referencia": "manualOperador_6110j_6125j_6130j.pdf"
        },
        {
          "nome": "6135J",
          "referencia": "manualOperador_6135j_6150j_6170j_6190j_6210j.pdf"
        },
        {
          "nome": "6150J",
          "referencia": "manualOperador_6135j_6150j_6170j_6190j_6210j.pdf"
        },
        {
          "nome": "6170J",
          "referencia": "manualOperador_6135j_6150j_6170j_6190j_6210j.pdf"
        },
        {
          "nome": "6190J",
          "referencia": "manualOperador_6135j_6150j_6170j_6190j_6210j.pdf"
        },
        {
          "nome": "6210J",
          "referencia": "manualOperador_6135j_6150j_6170j_6190j_6210j.pdf"
        }
      ]
    },
    "Série 7000": {
      "modelos": [
        {
          "nome": "7200J",
          "referencia": "manualOperador_7200J_7215J_7230J.pdf"
        },
        {
          "nome": "7215J",
          "referencia": "manualOperador_7200J_7215J_7230J.pdf"
        },
        {
          "nome": "7230J",
          "referencia": "manualOperador_7200J_7215J_7230J.pdf"
        }
      ]
    },
    "Série 8000": {
      "modelos": [
        {
          "nome": "8260R",
          "referencia": "manualOperador_8260r_8285r_8310r_8335r_8360r.pdf"
        },
        {
          "nome": "8285R",
          "referencia": "manualOperador_8260r_8285r_8310r_8335r_8360r.pdf"
        },
        {
          "nome": "8310R",
          "referencia": "manualOperador_8260r_8285r_8310r_8335r_8360r.pdf"
        },
        {
          "nome": "8335R",
          "referencia": "manualOperador_8260r_8285r_8310r_8335r_8360r.pdf"
        },
        {
          "nome": "8360R",
          "referencia": "manualOperador_8260r_8285r_8310r_8335r_8360r.pdf"
        }
      ]
    },
    "Série M": {
      "modelos": [
        {
          "nome": "6155M",
          "referencia": "manualOperador_6155M_6175M_6195M.pdf"
        },
        {
          "nome": "6175M",
          "referencia": "manualOperador_6155M_6175M_6195M.pdf"
        },
        {
          "nome": "6195M",
          "referencia": "manualOperador_6155M_6175M_6195M.pdf"
        }
      ]
    },
    "Pulverizadores": {
      "modelos": [
        {
          "nome": "4730",
          "referencia": "manualOperador_4730_4830.pdf"
        },
        {
          "nome": "4830",
          "referencia": "manualOperador_4730_4830.pdf"
        },
        {
          "nome": "M4030",
          "referencia": "manualOperador_M4040_M4030.pdf"
        },
        {
          "nome": "M4040",
          "referencia": "manualOperador_M4040_M4030.pdf"
        }
      ]
    },
    "Plantadeiras": {
      "modelos": [
        {
          "nome": "Plantadeira 1111",
          "referencia": "manualOperadorPlantadeira_1111_1113.pdf"
        },
        {
          "nome": "Plantadeira 1113",
          "referencia": "manualOperadorPlantadeira_1111_1113.pdf"
        },
        {
          "nome": "Família DB",
          "referencia": "manualOperadorPlantadeira_familiaDB.pdf"
        }
      ]
    }
  }
}

# Funções utilitárias para manipular dados de séries e modelos de máquinas agrícolas

def get_list_modelos(data):
    """
    Retorna uma lista de todos os modelos disponíveis no JSON.

    Args:
        data (dict): Dicionário contendo as séries e modelos.

    Returns:
        list: Lista de strings com os nomes dos modelos.
    """
    modelos = []
    for serie in data['series'].values():
        for modelo in serie['modelos']:
            modelos.append(modelo['nome'])
    return modelos


def get_series_by_model(data, model_name):
    """
    Retorna o nome da série em que um modelo específico está incluído.

    Args:
        data (dict): Dicionário contendo as séries e modelos.
        model_name (str): Nome do modelo que está sendo pesquisado.

    Returns:
        str or None: Nome da série correspondente ou None se não encontrado.
    """
    for serie_name, serie_data in data['series'].items():
        for modelo in serie_data['modelos']:
            if modelo['nome'] == model_name:
                return serie_name
    return None


def get_modelos_by_serie(data, serie_name):
    """
    Retorna todos os modelos pertencentes a uma série específica.

    Args:
        data (dict): Dicionário contendo as séries e modelos.
        serie_name (str): Nome da série que está sendo pesquisada.

    Returns:
        list: Lista de strings com os nomes dos modelos da série ou lista vazia se a série não existir.
    """
    if serie_name in data['series']:
        return [modelo['nome'] for modelo in data['series'][serie_name]['modelos']]
    return []


def get_referencia_by_model(data, model_name):
    """
    Retorna a referência (manual) associada a um modelo específico.

    Args:
        data (dict): Dicionário contendo as séries e modelos.
        model_name (str): Nome do modelo que está sendo pesquisado.

    Returns:
        str or None: Referência (nome do manual) associada ao modelo ou None se não encontrado.
    """
    for serie in data['series'].values():
        for modelo in serie['modelos']:
            if modelo['nome'] == model_name:
                return modelo['referencia']
    return None


def get_series(data):
    """
    Retorna uma lista com todas as séries disponíveis no JSON.

    Args:
        data (dict): Dicionário contendo as séries e modelos.

    Returns:
        list: Lista de strings com os nomes das séries.
    """
    return list(data['series'].keys())


def get_model_data(data, model_name):
    """
    Retorna os detalhes (nome e referência) de um modelo específico.

    Args:
        data (dict): Dicionário contendo as séries e modelos.
        model_name (str): Nome do modelo que está sendo pesquisado.

    Returns:
        dict or None: Dicionário contendo os dados do modelo (nome e referência) ou None se o modelo não for encontrado.
    """
    for serie in data['series'].values():
        for modelo in serie['modelos']:
            if modelo['nome'] == model_name:
                return modelo
    return None
