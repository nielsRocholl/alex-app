import streamlit as st
from modules.kenter_module import get_kenter_data
from modules.entsoe_module import get_energy_prices
from modules.battery_module import BatterySavingsCalculator
from utils.utils import *
from auth.authenticator import Authenticator

# Initialize the Authenticator
allowed_users = st.secrets["ALLOWED_USERS"].split(",")
authenticator = Authenticator(
    allowed_users=allowed_users,
    token_key=st.secrets["TOKEN_KEY"],
    client_secret=st.secrets["CLIENT_SECRET"],
    redirect_uri="https://nielsrocholl.streamlit.app/"  # Ensure this matches Google Cloud Console
)

def main():
    st.title("Energy Usage and Price Analysis")

    # Check authentication status
    authenticator.check_auth()

    # Show login/logout buttons in the sidebar
    with st.sidebar:
        if st.session_state.get("connected"):
            if st.button("Log out", use_container_width=True):
                authenticator.logout()
                st.rerun()
        else:
            auth_url = authenticator.get_auth_url()
            st.link_button("Login with Google", auth_url, use_container_width=True)

    # Only show the main content if the user is authenticated
    if st.session_state.get("connected"):
        st.write(f"Welcome! {st.session_state['user_info'].get('email')}")

        # Date inputs
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date")
        with col2:
            end_date = st.date_input("End Date")

        # Add fetch button
        if st.button("Fetch Data"):
            if start_date and end_date:
                # Validate dates
                valid, error_message = validate_dates(start_date, end_date)
                
                if not valid:
                    st.error(error_message)
                    return
                
                try:
                    with st.spinner('Fetching data...'):
                        # Get data
                        usage_df = get_kenter_data(
                            start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d'),
                            interval='15min'
                        )
                        
                        price_df = get_energy_prices(
                            start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d')
                        )    
                        
                        # Show usage and price plot
                        st.subheader("Energy Usage and Prices")
                        fig = create_plot(usage_df, price_df)
                        st.plotly_chart(fig, use_container_width=True)
                        
                        # Calculate and show costs and savings
                        st.subheader("Cost Analysis with Battery Storage")
                        
                        # Calculate daily costs
                        daily_costs = calculate_daily_costs(usage_df, price_df)
                        
                        # Calculate potential savings
                        battery_calculator = BatterySavingsCalculator()
                        savings = battery_calculator.arbitrage(usage_df, price_df)
                        
                        # Create and show the cost savings plot
                        cost_savings_fig = create_cost_savings_plot(daily_costs, savings)
                        st.plotly_chart(cost_savings_fig, use_container_width=True)
                        
                        # Show summary metrics
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            total_costs = daily_costs['cost'].sum()
                            st.metric("Total Costs (EUR)", f"{total_costs:.2f}")
                        with col2:
                            total_savings = savings['savings'].sum()
                            st.metric("Potential Savings (EUR)", f"{total_savings:.2f}")
                        with col3:
                            savings_percentage = (total_savings / total_costs * 100) if total_costs > 0 else 0
                            st.metric("Savings Percentage", f"{savings_percentage:.1f}%")
                        
                        # Show basic statistics
                        st.subheader("Usage Statistics")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            total_supply = usage_df[usage_df['type'] == 'supply']['value'].sum()
                            st.metric("Total Supply (kWh)", f"{total_supply:.2f}")
                        with col2:
                            total_return = usage_df[usage_df['type'] == 'return']['value'].sum()
                            st.metric("Total Return (kWh)", f"{total_return:.2f}")
                        with col3:
                            avg_price = price_df['price'].mean()
                            st.metric("Average Price (EUR/kWh)", f"{avg_price:.4f}")
                        
                except Exception as e:
                    st.error(f"Error fetching data: {str(e)}")
        else:
            st.info("Select dates and click 'Fetch Data' to view the analysis")
    else:
        st.warning("Please log in to access the app.")


if __name__ == "__main__":
    main()