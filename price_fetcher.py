import requests

def get_crypto_prices():
    """
    Fetches the current prices of Bitcoin (BTC), Ethereum (ETH), and Chainlink (LINK) in USD.
    """
    url = 'https://api.coingecko.com/api/v3/simple/price'
    params = {
        'ids': 'bitcoin,ethereum,chainlink',
        'vs_currencies': 'usd'
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        return {
            'bitcoin': data['bitcoin']['usd'],
            'ethereum': data['ethereum']['usd'],
            'link': data['chainlink']['usd']
        }

    except requests.exceptions.RequestException as e:
        print(f"Error fetching cryptocurrency prices: {e}")
        return None

if __name__ == "__main__":
    prices = get_crypto_prices()
    if prices:
        print(f"Bitcoin:  ${prices['bitcoin']:,.2f}")
        print(f"Ethereum: ${prices['ethereum']:,.2f}")
        print(f"LINK:     ${prices['link']:,.2f}")
    else:
        print("Failed to fetch prices.")
