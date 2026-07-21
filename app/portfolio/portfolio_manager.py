from app.services.market_data import MarketDataProvider


class PortfolioManager:

    @staticmethod
    def calculate_position(symbol: str, shares: int, buy_price: float):

        current_price = MarketDataProvider.get_stock_price(symbol)

        if current_price is None:
            print("❌ No fue posible obtener el precio actual.")
            return

        invested = shares * buy_price
        current_value = shares * current_price

        profit = current_value - invested

        percentage = (
            (current_price - buy_price) / buy_price
        ) * 100

        # Recomendación básica
        if percentage >= 3:
            recommendation = "VENDER"
            confidence = 85

        elif percentage <= -3:
            recommendation = "COMPRAR"
            confidence = 80

        else:
            recommendation = "MANTENER"
            confidence = 75

        print("=" * 60)
        print("📊 PORTAFOLIO DE INVERSIÓN")
        print("=" * 60)
        print(f"Activo           : {symbol}")
        print(f"Cantidad         : {shares}")
        print(f"Precio Compra    : ${buy_price:,.2f}")
        print(f"Precio Actual    : ${current_price:,.2f}")
        print(f"Valor Invertido  : ${invested:,.2f}")
        print(f"Valor Actual     : ${current_value:,.2f}")
        print(f"Variación        : {percentage:.2f}%")
        print(f"Ganancia/Pérdida : ${profit:,.2f}")
        print(f"Recomendación    : {recommendation}")
        print(f"Confianza IA     : {confidence}%")
        print("=" * 60)


if __name__ == "__main__":

    PortfolioManager.calculate_position(
        symbol="MINEROS",
        shares=73,
        buy_price=15440
    )