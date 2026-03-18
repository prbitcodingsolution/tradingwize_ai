"""
Data Validator - Validates stock data for accuracy and consistency
"""

from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime, timedelta
import re


class DataValidator:
    """Validates stock data from multiple sources"""
    
    @staticmethod
    def validate_financial_metrics(metrics: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Validate financial metrics for impossible or suspicious values
        
        Args:
            metrics: Dictionary of financial metrics
            
        Returns:
            Tuple of (validated_metrics, warnings)
        """
        warnings = []
        
        # Validate PE Ratio
        if metrics.get('pe_ratio') is not None:
            pe = metrics['pe_ratio']
            if pe < 0:
                warnings.append("⚠️ Negative PE ratio detected - company may have losses")
            elif pe > 1000:
                warnings.append("⚠️ Extremely high PE ratio (>1000) - likely data error")
                metrics['pe_ratio_confidence'] = 'low'
            elif pe < 1 and pe > 0:
                warnings.append("⚠️ Very low PE ratio (<1) - verify data accuracy or exceptional profits")
                metrics['pe_ratio_confidence'] = 'low'
            else:
                metrics['pe_ratio_confidence'] = 'medium'
        
        # Validate PB Ratio
        if metrics.get('pb_ratio') is not None:
            pb = metrics['pb_ratio']
            if pb < 0:
                warnings.append("⚠️ Negative PB ratio - data error")
                metrics['pb_ratio_confidence'] = 'low'
            elif pb > 50:
                warnings.append("⚠️ Extremely high PB ratio (>50) - verify data")
                metrics['pb_ratio_confidence'] = 'low'
            else:
                metrics['pb_ratio_confidence'] = 'medium'
        
        # Validate Debt-to-Equity
        if metrics.get('debt_to_equity') is not None:
            de = metrics['debt_to_equity']
            if de < 0:
                warnings.append("❌ Negative Debt-to-Equity ratio - data error")
                metrics['debt_to_equity_confidence'] = 'low'
            elif de > 10:
                warnings.append("⚠️ Very high Debt-to-Equity ratio (>10) - company is highly leveraged")
                metrics['debt_to_equity_confidence'] = 'medium'
            else:
                metrics['debt_to_equity_confidence'] = 'high'
        
        # Validate Profit Margin
        if metrics.get('profit_margin') is not None:
            pm = metrics['profit_margin']
            if pm < -100 or pm > 100:
                warnings.append("❌ Profit margin outside valid range (-100% to 100%) - data error")
                metrics['profit_margin_confidence'] = 'low'
            elif pm < 0:
                warnings.append("⚠️ Negative profit margin - company is loss-making")
                metrics['profit_margin_confidence'] = 'high'
            else:
                metrics['profit_margin_confidence'] = 'high'
        
        # Validate Total Liabilities vs Total Debt
        if metrics.get('total_liabilities') and metrics.get('total_debt'):
            if metrics['total_liabilities'] < metrics['total_debt']:
                warnings.append("❌ Total Liabilities < Total Debt - data inconsistency detected")
                metrics['balance_sheet_confidence'] = 'low'
            else:
                metrics['balance_sheet_confidence'] = 'high'
        
        # Validate Market Cap
        if metrics.get('market_cap') and metrics.get('current_price') and metrics.get('shares_outstanding'):
            calculated_market_cap = metrics['current_price'] * metrics['shares_outstanding']
            reported_market_cap = metrics['market_cap']
            
            # Allow 5% variance
            if abs(calculated_market_cap - reported_market_cap) / reported_market_cap > 0.05:
                warnings.append("⚠️ Market cap calculation mismatch - verify data")
                metrics['market_cap_confidence'] = 'low'
            else:
                metrics['market_cap_confidence'] = 'high'
        
        # Validate EPS
        if metrics.get('eps') is not None:
            eps = metrics['eps']
            if abs(eps) > 10000:
                warnings.append("⚠️ Extremely high EPS - verify data accuracy")
                metrics['eps_confidence'] = 'low'
            else:
                metrics['eps_confidence'] = 'medium'
        
        # Validate Revenue
        if metrics.get('revenue') is not None:
            revenue = metrics['revenue']
            if revenue < 0:
                warnings.append("❌ Negative revenue - data error")
                metrics['revenue_confidence'] = 'low'
            elif revenue == 0:
                warnings.append("⚠️ Zero revenue - company may be pre-revenue or data missing")
                metrics['revenue_confidence'] = 'low'
            else:
                metrics['revenue_confidence'] = 'medium'
        
        return metrics, warnings
    
    @staticmethod
    def check_data_freshness(last_fiscal_year_end: Optional[int]) -> Tuple[str, str]:
        """
        Check if data is fresh
        
        Args:
            last_fiscal_year_end: Unix timestamp of last fiscal year end
            
        Returns:
            Tuple of (freshness_status, message)
        """
        if not last_fiscal_year_end:
            return "unknown", "⚠️ Data freshness unknown"
        
        try:
            last_update = datetime.fromtimestamp(last_fiscal_year_end)
            days_old = (datetime.now() - last_update).days
            
            if days_old < 90:
                return "fresh", f"✅ Data is fresh (updated {days_old} days ago)"
            elif days_old < 180:
                return "stale", f"⚠️ Data is stale (updated {days_old} days ago)"
            else:
                return "very_stale", f"❌ Data is very stale (updated {days_old} days ago)"
        except Exception as e:
            return "error", f"❌ Error checking freshness: {e}"
    
    @staticmethod
    def validate_ceo_name(ceo_name: str) -> Tuple[str, str]:
        """
        Validate CEO name format
        
        Args:
            ceo_name: CEO name to validate
            
        Returns:
            Tuple of (confidence, message)
        """
        if not ceo_name or ceo_name == 'N/A':
            return "low", "⚠️ CEO information not available"
        
        # Check if name looks valid (has at least 2 words)
        words = ceo_name.strip().split()
        if len(words) < 2:
            return "low", "⚠️ CEO name may be incomplete"
        
        # Check for common placeholder text
        placeholders = ['unknown', 'not available', 'n/a', 'na', 'none', 'null']
        if ceo_name.lower() in placeholders:
            return "low", "⚠️ CEO information is placeholder"
        
        return "medium", "✅ CEO name format looks valid"
    
    @staticmethod
    def cross_validate_values(value1: float, value2: float, field_name: str, tolerance: float = 0.10) -> Tuple[bool, str]:
        """
        Cross-validate values from different sources
        
        Args:
            value1: Value from source 1
            value2: Value from source 2
            field_name: Name of the field being validated
            tolerance: Acceptable variance (default 10%)
            
        Returns:
            Tuple of (is_valid, message)
        """
        if value1 is None or value2 is None:
            return True, f"⚠️ {field_name}: One or both values missing"
        
        if value1 == 0 or value2 == 0:
            return True, f"⚠️ {field_name}: One value is zero"
        
        # Calculate percentage difference
        avg = (value1 + value2) / 2
        diff_pct = abs(value1 - value2) / avg
        
        if diff_pct <= tolerance:
            return True, f"✅ {field_name}: Values match within {tolerance*100}%"
        else:
            return False, f"❌ {field_name}: Values differ by {diff_pct*100:.1f}% (tolerance: {tolerance*100}%)"
    
    @staticmethod
    def validate_holdings(promoter: float, fii: float, dii: float) -> Tuple[bool, List[str]]:
        """
        Validate shareholding percentages
        
        Args:
            promoter: Promoter holding %
            fii: FII holding %
            dii: DII holding %
            
        Returns:
            Tuple of (is_valid, warnings)
        """
        warnings = []
        
        # Check if values are in valid range (0-100%)
        for name, value in [("Promoter", promoter), ("FII", fii), ("DII", dii)]:
            if value is not None:
                if value < 0 or value > 100:
                    warnings.append(f"❌ {name} holding {value}% is outside valid range (0-100%)")
                    return False, warnings
        
        # Check if total is reasonable (should be <= 100%)
        if all(v is not None for v in [promoter, fii, dii]):
            total = promoter + fii + dii
            if total > 100:
                warnings.append(f"❌ Total holdings ({total}%) exceed 100% - data error")
                return False, warnings
            elif total < 50:
                warnings.append(f"⚠️ Total holdings ({total}%) are low - remaining held by public/others")
        
        return True, warnings
    
    @staticmethod
    def validate_price_data(current_price: float, high_52w: float, low_52w: float) -> Tuple[bool, List[str]]:
        """
        Validate price data consistency
        
        Args:
            current_price: Current stock price
            high_52w: 52-week high
            low_52w: 52-week low
            
        Returns:
            Tuple of (is_valid, warnings)
        """
        warnings = []
        
        if current_price is None or high_52w is None or low_52w is None:
            warnings.append("⚠️ Price data incomplete")
            return True, warnings
        
        # Current price should be between 52w high and low
        if current_price > high_52w:
            warnings.append(f"❌ Current price (₹{current_price}) > 52-week high (₹{high_52w}) - data error")
            return False, warnings
        
        if current_price < low_52w:
            warnings.append(f"❌ Current price (₹{current_price}) < 52-week low (₹{low_52w}) - data error")
            return False, warnings
        
        # 52w high should be > 52w low
        if high_52w <= low_52w:
            warnings.append(f"❌ 52-week high (₹{high_52w}) <= 52-week low (₹{low_52w}) - data error")
            return False, warnings
        
        return True, warnings
    
    @staticmethod
    def generate_data_quality_report(metrics: Dict[str, Any], warnings: List[str]) -> str:
        """
        Generate a data quality report
        
        Args:
            metrics: Validated metrics with confidence scores
            warnings: List of validation warnings
            
        Returns:
            Formatted data quality report
        """
        if not warnings:
            return "✅ **Data Quality**: All metrics passed validation checks"
        
        report = "⚠️ **Data Quality Warnings**:\n\n"
        
        # Group warnings by severity
        errors = [w for w in warnings if w.startswith("❌")]
        warnings_list = [w for w in warnings if w.startswith("⚠️")]
        
        if errors:
            report += "**Critical Issues**:\n"
            for error in errors:
                report += f"{error}\n"
            report += "\n"
        
        if warnings_list:
            report += "**Warnings**:\n"
            for warning in warnings_list:
                report += f"{warning}\n"
            report += "\n"
        
        # Add confidence summary
        confidence_fields = {k: v for k, v in metrics.items() if k.endswith('_confidence')}
        if confidence_fields:
            report += "**Data Confidence Levels**:\n"
            for field, confidence in confidence_fields.items():
                field_name = field.replace('_confidence', '').replace('_', ' ').title()
                emoji = "✅" if confidence == "high" else "⚠️" if confidence == "medium" else "❌"
                report += f"{emoji} {field_name}: {confidence.title()}\n"
        
        return report


# Convenience functions
def validate_stock_data(data: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """
    Main validation function - validates all stock data
    
    Args:
        data: Stock data dictionary
        
    Returns:
        Tuple of (validated_data, quality_report)
    """
    validator = DataValidator()
    
    # Validate financial metrics
    validated_data, warnings = validator.validate_financial_metrics(data)
    
    # Check data freshness
    if 'last_fiscal_year_end' in data:
        freshness, freshness_msg = validator.check_data_freshness(data['last_fiscal_year_end'])
        validated_data['data_freshness'] = freshness
        if freshness != "fresh":
            warnings.append(freshness_msg)
    
    # Validate CEO name
    if 'ceo' in data:
        ceo_confidence, ceo_msg = validator.validate_ceo_name(data['ceo'])
        validated_data['ceo_confidence'] = ceo_confidence
        if ceo_confidence == "low":
            warnings.append(ceo_msg)
    
    # Validate holdings
    if all(k in data for k in ['promoter_holding', 'fii_holding', 'dii_holding']):
        holdings_valid, holdings_warnings = validator.validate_holdings(
            data['promoter_holding'],
            data['fii_holding'],
            data['dii_holding']
        )
        warnings.extend(holdings_warnings)
    
    # Validate price data
    if all(k in data for k in ['current_price', 'high_52w', 'low_52w']):
        price_valid, price_warnings = validator.validate_price_data(
            data['current_price'],
            data['high_52w'],
            data['low_52w']
        )
        warnings.extend(price_warnings)
    
    # Generate quality report
    quality_report = validator.generate_data_quality_report(validated_data, warnings)
    
    return validated_data, quality_report


if __name__ == "__main__":
    # Test the validator
    test_data = {
        'pe_ratio': 0.78,
        'pb_ratio': 0.23,
        'debt_to_equity': 0.9,
        'profit_margin': -5.2,
        'total_liabilities': 537,  # Cr
        'total_debt': 24000,  # Cr
        'eps': 155,
        'revenue': 20000,
        'promoter_holding': 19.0,
        'fii_holding': 10.37,
        'dii_holding': 12.81,
        'current_price': 95,
        'high_52w': 423,
        'low_52w': 92,
        'ceo': 'Vijesh Babu Thota',
        'last_fiscal_year_end': 1640995200  # Jan 2022 (very stale)
    }
    
    validated_data, quality_report = validate_stock_data(test_data)
    
    print("=" * 60)
    print("DATA VALIDATION TEST")
    print("=" * 60)
    print(quality_report)
    print("=" * 60)
