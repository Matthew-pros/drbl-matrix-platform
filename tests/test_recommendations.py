import pandas as pd
from src.config import CostConfig, StrategyConfig
from src.models import ModelName, PortfolioState
from src.services.recommendation_service import recommend

def test_recommendation_includes_source_and_historical_mode(sample_ohlcv):
    state=PortfolioState(ModelName.ALM,100_000)
    rec=recommend(ModelName.ALM,{"SPY":sample_ohlcv,"QQQ":sample_ohlcv},state,StrategyConfig(),CostConfig(),latest_timestamp=sample_ohlcv.index[-1].to_pydatetime())
    assert rec.source=="Yahoo Finance"
    assert rec.data_mode.value=="HISTORICAL"
