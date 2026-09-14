# academics/services/recommendation_service.py
"""
AI Recommendation service - Generates natural language recommendations
"""


def generate_section_recommendation(summary_data):
    """
    Generate AI recommendation based on section summary data.
    
    Args:
        summary_data: dict with keys:
            - section_name (str)
            - subject_name (str)
            - average_grade (float)
            - passing_rate (float)
            - excellent_rate (float)
            - at_risk_count (int)
            - total_students (int)
            - trend_direction (str)
            - trend_slope (float)
            - category (str)
    
    Returns:
        dict: {
            'summary': str,
            'insights': str,
            'recommendations': str,
            'confidence': float
        }
    """
    category = summary_data.get('category', 'STANDARD')
    avg_grade = summary_data.get('average_grade', 0)
    passing_rate = summary_data.get('passing_rate', 0)
    excellent_rate = summary_data.get('excellent_rate', 0)
    at_risk_count = summary_data.get('at_risk_count', 0)
    total_students = summary_data.get('total_students', 1)
    trend = summary_data.get('trend_direction', 'stable')
    subject_name = summary_data.get('subject_name', '')
    section_name = summary_data.get('section_name', '')
    
    risk_percent = (at_risk_count / total_students) * 100 if total_students > 0 else 0
    
    # ========== ONE SENTENCE SUMMARY ==========
    if category == 'EXCELLENCE':
        one_sentence = (
            f"{section_name} is performing at an **Excellence Track** level in {subject_name} "
            f"with a {avg_grade}% average and {excellent_rate}% of students scoring above 90%."
        )
    elif category == 'INTERVENTION':
        one_sentence = (
            f"{section_name} requires **immediate intervention** in {subject_name} "
            f"with only {passing_rate}% passing rate and {at_risk_count} student(s) at risk of failing."
        )
    else:
        one_sentence = (
            f"{section_name} is on **Standard Track** in {subject_name} "
            f"with {avg_grade}% average and {passing_rate}% passing rate."
        )
    
    # ========== KEY INSIGHTS ==========
    insights = []
    
    if excellent_rate > 50:
        insights.append(f"🎯 {excellent_rate}% of students are performing at an outstanding level (>90%)")
    elif excellent_rate > 25:
        insights.append(f"📈 {excellent_rate}% of students are above 90%, showing strong potential")
    
    if risk_percent > 30:
        insights.append(f"⚠️ {at_risk_count} students ({risk_percent}%) are below the passing threshold - URGENT")
    elif risk_percent > 20:
        insights.append(f"⚠️ {at_risk_count} students ({risk_percent}%) need additional support")
    elif risk_percent > 0:
        insights.append(f"📋 {at_risk_count} student(s) require targeted intervention")
    
    if trend == 'improving':
        insights.append(f"📊 Grades are showing improvement (trend: +{summary_data.get('trend_slope', 0)})")
    elif trend == 'declining':
        insights.append(f"📉 Grades are declining (trend: {summary_data.get('trend_slope', 0)}) - immediate attention recommended")
    elif trend == 'stable':
        insights.append("📊 Grades have remained stable across quarters")
    
    if passing_rate == 100 and category == 'EXCELLENCE':
        insights.append("🏆 Perfect passing rate achieved - excellent teacher performance")
    
    if not insights:
        insights.append("📋 Performance is within expected range for Standard Track")
    
    # ========== RECOMMENDATIONS ==========
    recommendations = []
    
    if category == 'EXCELLENCE':
        recommendations.append("🚀 **Accelerate**: Consider advanced curriculum or enrichment activities")
        recommendations.append("🏅 **Recognize**: Nominate top students for academic competitions")
        recommendations.append("📚 **Document**: Save teaching strategies for replication to other sections")
        
        if at_risk_count > 0:
            recommendations.append(f"🎯 **Target**: Provide focused support to {at_risk_count} student(s) below 90%")
        
        if excellent_rate >= 75:
            recommendations.append("⭐ **Challenge**: Assign independent research projects to high performers")
    
    elif category == 'INTERVENTION':
        recommendations.append("👀 **Observe**: Schedule a principal observation of this class within 2 weeks")
        recommendations.append("👨‍🏫 **Support**: Assign an experienced mentor teacher to assist the subject teacher")
        recommendations.append(f"📖 **Remediate**: Implement daily {30 if risk_percent > 30 else 20}-minute remediation sessions")
        recommendations.append("👪 **Engage**: Schedule parent-teacher conferences for all at-risk students")
        
        if trend == 'declining':
            recommendations.append("🔍 **Investigate**: Review teaching methodology and curriculum pacing")
        
        recommendations.append("📝 **Monitor**: Track weekly progress for the next 4 weeks")
    
    else:  # STANDARD
        recommendations.append("✅ **Maintain**: Continue current instructional strategies")
        
        if trend == 'declining':
            recommendations.append("🔍 **Investigate root causes** of grade decline before next quarter")
        elif trend == 'improving':
            recommendations.append("📈 **Reinforce**: Identify and strengthen what's working")
        
        recommendations.append(f"🎯 **Goal**: Aim to move {min(25, int(100 - excellent_rate))}% more students to Excellence bracket")
        
        if at_risk_count > 0:
            recommendations.append(f"🆘 **Intervene**: Provide targeted support to {at_risk_count} struggling student(s)")
        
        if passing_rate < 85 and passing_rate >= 75:
            recommendations.append("📊 **Analyze**: Review which topics are causing most failures")
    
    # ========== CONFIDENCE SCORE ==========
    confidence = 0.85
    if total_students < 10:
        confidence -= 0.10
    if trend == 'insufficient_data':
        confidence -= 0.15
    if category == 'INTERVENTION':
        confidence = min(0.95, confidence + 0.05)  # More confident about intervention needs
    
    confidence = max(0.5, min(0.98, confidence))
    
    return {
        'summary': one_sentence,
        'insights': '\n'.join(insights),
        'recommendations': '\n'.join(recommendations),
        'confidence': round(confidence, 2)
    }


def generate_student_recommendation(student_name, current_grade, trend, risk_factors):
    """
    Generate recommendation for an individual student
    
    Args:
        student_name: Name of the student
        current_grade: Current grade percentage
        trend: 'improving', 'declining', 'stable', or 'erratic'
        risk_factors: List of risk factors identified
    
    Returns:
        dict: {
            'summary': str,
            'recommendations': str
        }
    """
    if current_grade >= 90:
        summary = f"{student_name} is excelling with {current_grade}%."
        recommendations = "Continue challenging work. Consider honors track recommendation."
    
    elif current_grade >= 75:
        if trend == 'improving':
            summary = f"{student_name} is on track with {current_grade}% and showing improvement."
            recommendations = "Positive trajectory. Continue current support strategies."
        elif trend == 'declining':
            summary = f"{student_name} is passing but grades are declining from {current_grade}%."
            recommendations = "Schedule teacher-student conference to identify barriers to learning."
        else:
            summary = f"{student_name} is meeting expectations with {current_grade}%."
            recommendations = "Maintain current approach. Set goal to reach 85% next quarter."
    
    else:
        summary = f"{student_name} is at risk with {current_grade}%."
        recommendations = "URGENT: Schedule parent conference. Assign peer tutor. Implement daily monitoring."
    
    # Add specific recommendations based on risk factors
    if 'attendance' in str(risk_factors).lower():
        recommendations += " Address attendance concerns with parents."
    if 'declining' in str(risk_factors).lower():
        recommendations += " Review recent assessments to identify gaps."
    
    return {
        'summary': summary,
        'recommendations': recommendations
    }