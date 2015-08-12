from flask import render_template, request, redirect, url_for, abort, session, flash
from flask_login import login_required, current_user, current_app

from dmutils.apiclient import APIError, HTTPError
from dmutils import flask_featureflags
from dmutils.email import send_email, generate_token, MandrillException

from ...main import main
from ... import data_api_client
from ..forms.suppliers import EditSupplierForm, EditContactInformationForm, \
    DunsNumberForm, CompaniesHouseNumberForm, CompanyContactDetailsForm, CompanyNameForm, EmailAddressForm
from .users import get_current_suppliers_users


@main.route('')
@login_required
@flask_featureflags.is_active_feature('SUPPLIER_DASHBOARD',
                                      redirect='.list_services')
def dashboard():
    template_data = main.config['BASE_TEMPLATE_DATA']

    try:
        supplier = data_api_client.get_supplier(
            current_user.supplier_id
        )['suppliers']
        supplier['contact'] = supplier['contactInformation'][0]
    except APIError as e:
        abort(e.status_code)

    return render_template(
        "suppliers/dashboard.html",
        supplier=supplier,
        users=get_current_suppliers_users(),
        **template_data
    ), 200


@main.route('/edit', methods=['GET'])
@login_required
@flask_featureflags.is_active_feature('EDIT_SUPPLIER_PAGE')
def edit_supplier(supplier_form=None, contact_form=None, error=None):
    template_data = main.config['BASE_TEMPLATE_DATA']

    try:
        supplier = data_api_client.get_supplier(
            current_user.supplier_id
        )['suppliers']
    except APIError as e:
        abort(e.status_code)

    if supplier_form is None:
        supplier_form = EditSupplierForm(
            description=supplier['description'],
            clients=supplier['clients']
        )
        contact_form = EditContactInformationForm(
            prefix='contact_',
            **supplier['contactInformation'][0]
        )

    return render_template(
        "suppliers/edit_supplier.html",
        error=error,
        supplier_form=supplier_form,
        contact_form=contact_form,
        **template_data
    ), 200


@main.route('/edit', methods=['POST'])
@login_required
@flask_featureflags.is_active_feature('EDIT_SUPPLIER_PAGE')
def update_supplier():
    # FieldList expects post parameter keys to have number suffixes
    # (eg client-0, client-1 ...), which is incompatible with how
    # JS list-entry plugin generates input names. So instead of letting
    # the form search for request keys we pass in the values directly as data
    supplier_form = EditSupplierForm(
        formdata=None,
        description=request.form['description'],
        clients=filter(None, request.form.getlist('clients'))
    )

    contact_form = EditContactInformationForm(prefix='contact_')

    if not (supplier_form.validate_on_submit() and
            contact_form.validate_on_submit()):
        return edit_supplier(supplier_form=supplier_form,
                             contact_form=contact_form)

    try:
        data_api_client.update_supplier(
            current_user.supplier_id,
            supplier_form.data,
            current_user.email_address
        )

        data_api_client.update_contact_information(
            current_user.supplier_id,
            contact_form.id.data,
            contact_form.data,
            current_user.email_address
        )
    except APIError as e:
        return edit_supplier(supplier_form=supplier_form,
                             contact_form=contact_form,
                             error=e.message)

    return redirect(url_for(".dashboard"))


@main.route('/create', methods=['GET'])
def create_new_supplier():
    template_data = main.config['BASE_TEMPLATE_DATA']
    return render_template(
        "suppliers/create_new_supplier.html",
        **template_data
    ), 200


@main.route('/duns-number', methods=['GET'])
def duns_number():
    template_data = main.config['BASE_TEMPLATE_DATA']
    form = DunsNumberForm()

    if form.duns_number.name in session:
        form.duns_number.data = session[form.duns_number.name]

    return render_template(
        "suppliers/duns_number.html",
        form=form,
        **template_data
    ), 200


@main.route('/duns-number', methods=['POST'])
def submit_duns_number():
    form = DunsNumberForm()
    template_data = main.config['BASE_TEMPLATE_DATA']

    if form.validate_on_submit():

        suppliers = data_api_client.find_suppliers(duns_number=form.duns_number.data)
        if len(suppliers["suppliers"]) > 0:
            form.duns_number.errors = ["Duns number already used"]
            return render_template(
                "suppliers/duns_number.html",
                form=form,
                **template_data
            ), 400
        session[form.duns_number.name] = form.duns_number.data
        return redirect(url_for(".companies_house_number"))
    else:
        return render_template(
            "suppliers/duns_number.html",
            form=form,
            **template_data
        ), 400


@main.route('/companies-house-number', methods=['GET'])
def companies_house_number():
    template_data = main.config['BASE_TEMPLATE_DATA']
    form = CompaniesHouseNumberForm()

    if form.companies_house_number.name in session:
        form.companies_house_number.data = session[form.companies_house_number.name]

    return render_template(
        "suppliers/companies_house_number.html",
        form=form,
        **template_data
    ), 200


@main.route('/companies-house-number', methods=['POST'])
def submit_companies_house_number():
    form = CompaniesHouseNumberForm()

    template_data = main.config['BASE_TEMPLATE_DATA']

    if form.validate_on_submit():
        if form.companies_house_number.data:
            session[form.companies_house_number.name] = form.companies_house_number.data
        else:
            session.pop(form.companies_house_number.name, None)
        return redirect(url_for(".company_name"))
    else:
        return render_template(
            "suppliers/companies_house_number.html",
            form=form,
            **template_data
        ), 400


@main.route('/company-name', methods=['GET'])
def company_name():
    template_data = main.config['BASE_TEMPLATE_DATA']
    form = CompanyNameForm()

    if form.company_name.name in session:
        form.company_name.data = session[form.company_name.name]

    return render_template(
        "suppliers/company_name.html",
        form=form,
        **template_data
    ), 200


@main.route('/company-name', methods=['POST'])
def submit_company_name():
    form = CompanyNameForm()
    template_data = main.config['BASE_TEMPLATE_DATA']

    if form.validate_on_submit():
        session[form.company_name.name] = form.company_name.data
        return redirect(url_for(".company_contact_details"))
    else:
        return render_template(
            "suppliers/company_name.html",
            form=form,
            **template_data
        ), 400


@main.route('/company-contact-details', methods=['GET'])
def company_contact_details():
    template_data = main.config['BASE_TEMPLATE_DATA']
    form = CompanyContactDetailsForm()

    if form.email_address.name in session:
        form.email_address.data = session[form.email_address.name]

    if form.phone_number.name in session:
        form.phone_number.data = session[form.phone_number.name]

    if form.contact_name.name in session:
        form.contact_name.data = session[form.contact_name.name]

    return render_template(
        "suppliers/company_contact_details.html",
        form=form,
        **template_data
    ), 200


@main.route('/company-contact-details', methods=['POST'])
def submit_company_contact_details():
    form = CompanyContactDetailsForm()

    template_data = main.config['BASE_TEMPLATE_DATA']

    if form.validate_on_submit():
        session[form.email_address.name] = form.email_address.data
        session[form.phone_number.name] = form.phone_number.data
        session[form.contact_name.name] = form.contact_name.data
        return redirect(url_for(".company_summary"))
    else:
        return render_template(
            "suppliers/company_contact_details.html",
            form=form,
            **template_data
        ), 400


@main.route('/company-summary', methods=['GET'])
def company_summary():
    template_data = main.config['BASE_TEMPLATE_DATA']
    return render_template(
        "suppliers/company_summary.html",
        **template_data
    ), 200


@main.route('/company-summary', methods=['POST'])
def submit_company_summary():
    template_data = main.config['BASE_TEMPLATE_DATA']

    required_fields = [
        "email_address",
        "phone_number",
        "contact_name",
        "duns_number",
        "company_name"
    ]

    missing_fields = [field for field in required_fields if field not in session]

    if not missing_fields:
        try:
            supplier = {
                "name": session["company_name"],
                "dunsNumber": str(session["duns_number"]),
                "contactInformation": [{
                    "email": session["email_address"],
                    "phoneNumber": session["phone_number"],
                    "contactName": session["contact_name"]
                }]
            }

            if session.get("companies_house_number", None):
                supplier["companiesHouseNumber"] = session.get("companies_house_number")

            supplier = data_api_client.create_supplier(supplier)
            session.clear()
            session['email_company_name'] = supplier['suppliers']['name']
            session['email_supplier_id'] = supplier['suppliers']['id']
            return redirect(url_for('.create_your_account'), 302)
        except HTTPError as e:
            current_app.logger.error(str(e))
            abort(503)
    else:
        return render_template(
            "suppliers/company_summary.html",
            missing_fields=missing_fields,
            **template_data
        ), 400


@main.route('/create-your-account', methods=['GET'])
def create_your_account():
    form = EmailAddressForm()

    template_data = main.config['BASE_TEMPLATE_DATA']

    return render_template(
        "suppliers/create_your_account.html",
        form=form,
        **template_data
    ), 200


@main.route('/create-your-account', methods=['POST'])
def submit_create_your_account():
    template_data = main.config['BASE_TEMPLATE_DATA']
    form = EmailAddressForm()

    required_fields = [
        "email_supplier_id",
        "email_company_name",
    ]

    missing_fields = [field for field in required_fields if field not in session]

    if missing_fields:
        current_app.logger.info("Failed to create user as broken session", session)
        abort(503)

    if form.validate_on_submit():
        token = generate_token(
            {
                "email_address":  form.email_address.data,
                "supplier_id": session['email_supplier_id'],
                "supplier_name": session['email_company_name']
            },
            current_app.config['SHARED_EMAIL_KEY'],
            current_app.config['INVITE_EMAIL_SALT']
        )

        url = url_for('main.create_user', encoded_token=token, _external=True)

        email_body = render_template(
            "emails/create_user_email.html",
            company_name=session['email_company_name'],
            url=url
        )
        try:
            send_email(
                form.email_address.data,
                email_body,
                current_app.config['DM_MANDRILL_API_KEY'],
                current_app.config['CREATE_USER_SUBJECT'],
                current_app.config['RESET_PASSWORD_EMAIL_FROM'],
                current_app.config['RESET_PASSWORD_EMAIL_NAME'],
                ["user-creation"]
            )
            session.clear()
            session['email_sent_to'] = form.email_address.data
            return redirect(url_for('.create_your_account_complete'), 302)
        except MandrillException as e:
            current_app.logger.error(
                "Create user email failed to send error {} to {} supplier {} supplier id {} ".format(
                    str(e),
                    form.email_address.data,
                    session['email_company_name'],
                    session['email_supplier_id'])
            )
            abort(503, "Failed to send user creation email")
    else:
        return render_template(
            "suppliers/create_your_account.html",
            form=form,
            **template_data
        ), 400


@main.route('/create-your-account-complete', methods=['GET'])
def create_your_account_complete():
    template_data = main.config['BASE_TEMPLATE_DATA']

    email_address = session['email_sent_to']
    session.clear()
    return render_template(
        "suppliers/create_your_account_complete.html",
        email_address=email_address,
        **template_data
    ), 200
