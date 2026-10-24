from src.models import PortfolioState, ModelName
from src.config import StrategyConfig
from src.strategies.drbl_matrix import generate_matrix_recommendation

def test_matrix_missing_data_not_available():
    state=PortfolioState(ModelName.DRBL_MATRIX,100_000)
    rec=generate_matrix_recommendation({},state,StrategyConfig())
    assert not rec.available

def test_more_than_one_holding_requires_review(sample_ohlcv):
    from src.models import Position
    state=PortfolioState(ModelName.DRBL_MATRIX,10_000,positions={"SPY":Position("SPY",50_000,500),"QQQ":Position("QQQ",40_000,300)})
    rec=generate_matrix_recommendation({"SPY":sample_ohlcv,"QQQ":sample_ohlcv,"GLD":sample_ohlcv,"IBIT":sample_ohlcv},state,StrategyConfig())
    assert rec.action=="REVIEW" and not rec.available
